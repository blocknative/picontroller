#pragma version 0.4.1
#pragma optimize gas

interface IOracle:
    def get(systemid: uint8, cid: uint64, typ: uint16) -> (uint256, uint64, uint48): view
    def storeValuesWithReceipt(dat: Bytes[MAX_PAYLOAD_SIZE]) -> DynArray[RecordReceipt, MAX_PAYLOADS]: payable

struct RecordReceipt:
    systemid: uint8
    cid: uint64
    typ: uint16
    old_height: uint64
    old_timestamp: uint48
    old_value: uint240
    new_height: uint64
    new_timestamp: uint48
    new_value: uint240

event OracleUpdated:
    updater: address
    system_id: uint8
    chain_id: uint64
    new_value: uint240
    raw_deviation: uint240
    time_since: uint48
    time_reward: uint256
    deviation_reward: uint256
    reward_mult: int256

event RewardsToggled:
    rewards_on: bool

event RewardsFreeze:
    rewards_frozen: bool

struct Scale:
    system_id: uint8
    chain_id: uint64
    scale: uint256

struct Coefficients:
    zero: int96
    one: int96
    two: int96
    three: int96

struct ControlOutput:
    kp: int80
    ki: int80
    co_bias: int80

struct EnhancedReward:
    system_id: uint8
    chain_id: uint64
    height: uint64
    gas_price: uint240
    time_reward: uint256
    deviation_reward: uint256

struct TotalRewards:
    address: address
    total_rewards: uint256

EIGHTEEN_DECIMAL_NUMBER: constant(int256) = 10**18
THIRTY_SIX_DECIMAL_NUMBER: constant(int256) = 10**36
EIGHTEEN_DECIMAL_NUMBER_U: constant(uint256) = 10**18

BASEFEE_REWARD_TYPE: public(constant(uint16)) = 107
MAX_PAYLOADS: public(constant(uint256)) = 32
MAX_UPDATERS: public(constant(uint32)) = 2**18
MAX_PAYLOAD_SIZE: public(constant(uint256)) = 16384
EMA_ALPHA: public(constant(uint256)) = 818181818181818176 # 1 - 2/11
ALPHA_COMP: constant(uint256) = EIGHTEEN_DECIMAL_NUMBER_U - EMA_ALPHA

authorities: public(HashMap[address, bool])

tip_reward_type: public(uint16)

control_output: public(ControlOutput)

output_upper_bound: public(int256)
output_lower_bound: public(int256)
target_time_since: public(uint256)
min_reward: public(uint256)
max_reward: public(uint256)
min_time_reward: public(int256)
max_time_reward: public(int256)
min_deviation_reward: public(int256)
max_deviation_reward: public(int256)
min_window_size: public(uint32)
has_updated: public(HashMap[address, bool])
updaters: address[MAX_UPDATERS]
n_updaters:  public(uint32)

# if frozen, don't allow any updates
frozen: public(bool)

# if rewards_off, allow updates, but w/o rewards
rewards_enabled: public(bool)
oracle: public(IOracle)

error_integral: public(HashMap[uint72, int256])
last_output: public(HashMap[uint72, int256])

rewards: public(HashMap[address, uint256])
total_rewards: public(uint256)
scales: public(HashMap[uint72, uint256])
count: public(HashMap[uint72, uint32])

interval_ema: public(HashMap[uint72, uint256]) # EMA

coeff: public(Coefficients)

@deploy
def __init__(_kp: int80, _ki: int80, _co_bias: int80,
             _output_upper_bound: int256, _output_lower_bound: int256, _target_time_since: uint256,
             _tip_reward_type: uint16,
             _min_reward: uint256, _max_reward: uint256,
             _min_window_size: uint32, oracle: address,
             _coeff: int96[4]):
    #
    assert _output_upper_bound >= _output_lower_bound, "RewardController/invalid-bounds"
    assert oracle.is_contract, "Oracle address is not a contract"
    assert _target_time_since > 0, "target_time_since must be positive"

    self.authorities[msg.sender] = True
    self.control_output = ControlOutput(kp=_kp, ki=_ki, co_bias=_co_bias)
    self.output_upper_bound = _output_upper_bound
    self.output_lower_bound = _output_lower_bound
    self.target_time_since = _target_time_since
    self.tip_reward_type = _tip_reward_type
    self.min_reward = _min_reward
    self.max_reward = _max_reward
    self.min_time_reward = convert(_min_reward//2, int256)
    self.max_time_reward = convert(_max_reward//2, int256)
    self.min_deviation_reward = convert(_min_reward//2, int256)
    self.max_deviation_reward = convert(_max_reward//2, int256)
    self.min_window_size = _min_window_size
    self.oracle = IOracle(oracle)
    self.coeff = Coefficients(zero=_coeff[0], one=_coeff[1], two=_coeff[2], three=_coeff[3])
    log RewardsToggled(rewards_on=False)

@external
def add_authority(account: address):
    assert self.authorities[msg.sender]
    self.authorities[account] = True
    
@external
def remove_authority(account: address):
    assert self.authorities[msg.sender]
    self.authorities[account] = False

@external
def set_scales(scales: DynArray[Scale, 64]):
    assert self.authorities[msg.sender]
    scid: uint72 = 0
    for s: Scale in scales:
        scid = convert(shift(convert(s.chain_id, uint256), 8) | convert(s.system_id, uint256), uint72)
        assert s.scale != 0, "scale can't be zero"
        self.scales[scid] = s.scale

@external
@view
def get_scale(system_id: uint8, chain_id: uint64) -> uint256:
    scid: uint72 = convert(shift(convert(chain_id, uint256), 8) | convert(system_id, uint256), uint72)
    return self.scales[scid]

@external
def set_scale(system_id: uint8, chain_id: uint64, scale: uint256):
    assert self.authorities[msg.sender]
    scid: uint72 = convert(shift(convert(chain_id, uint256), 8) | convert(system_id, uint256), uint72)
    assert scale != 0, "scale can't be zero"
    self.scales[scid] = scale

@external
def freeze():
    assert self.authorities[msg.sender]
    self.frozen = True
    log RewardsFreeze(rewards_frozen=True)

@external
def unfreeze():
    assert self.authorities[msg.sender]
    self.frozen = False
    log RewardsFreeze(rewards_frozen=False)

@external
def enable_rewards():
    assert self.authorities[msg.sender]
    self.rewards_enabled = True
    log RewardsToggled(rewards_on=True)

@external
def disable_rewards():
    assert self.authorities[msg.sender]
    self.rewards_enabled = False
    log RewardsToggled(rewards_on=False)

@external
def modify_parameters_addr(parameter: String[32], addr: address):
    assert self.authorities[msg.sender]
    if (parameter == "oracle"):
        assert addr.is_contract, "Oracle address is not a contract"
        self.oracle = IOracle(addr)
    else:
        raise "RewardController/modify-unrecognized-param"

@external
def modify_parameters_int(parameter: String[32], val: int256):
    assert self.authorities[msg.sender]
    if (parameter == "output_upper_bound"):
        assert val > self.output_lower_bound, "RewardController/invalid-output_upper_bound"
        self.output_upper_bound = val
    elif (parameter == "output_lower_bound"):
        assert val < self.output_upper_bound, "RewardController/invalid-output_lower_bound"
        self.output_lower_bound = val
    else:
        raise "RewardController/modify-unrecognized-param"

@external
def modify_parameters_control_output(parameter: String[32], val: int80):
    assert self.authorities[msg.sender]
    if (parameter == "kp"):
        self.control_output = ControlOutput(kp=val, ki=self.control_output.ki, co_bias=self.control_output.co_bias)
    elif (parameter == "ki"):
        self.control_output = ControlOutput(kp=self.control_output.kp, ki=val, co_bias=self.control_output.co_bias)
    elif (parameter == "co_bias"):
        self.control_output = ControlOutput(kp=self.control_output.kp, ki=self.control_output.ki, co_bias=val)
    else:
        raise "RewardController/modify-unrecognized-param"

@external
def modify_parameters_uint(parameter: String[32], val: uint256):
    assert self.authorities[msg.sender]
    if (parameter == "target_time_since"):
        assert val > 0, "target_time_since must be positive"
        self.target_time_since = val
    elif (parameter == "min_reward"):
        assert val < self.max_reward, "RewardController/invalid-min_reward"
        self.min_reward = val
    elif (parameter == "max_reward"):
        assert val > self.min_reward, "RewardController/invalid-max_reward"
        self.max_reward = val
    else:
        raise "RewardController/modify-unrecognized-param"

@internal
@view
def _bound_pi_output(pi_output: int256) -> int256:
    lb: int256 = self.output_lower_bound 
    ub: int256 = self.output_upper_bound

    if pi_output < lb:
        return lb
    elif pi_output > ub:
        return ub

    return pi_output

@external
@view
def bound_pi_output(pi_output: int256) -> int256:
    return self._bound_pi_output(pi_output)

@external
@view
def clamp_error_integral(bounded_pi_output:int256, error_integral: int256, new_error_integral: int256, new_area: int256) -> int256:
    return self._clamp_error_integral(bounded_pi_output, error_integral, new_error_integral, new_area)

@internal
@view
def _clamp_error_integral(
    bounded_pi_output: int256,
    error_integral:    int256,
    new_error_integral: int256,
    new_area:           int256
) -> int256:
    # This logic is strictly for a *reverse-acting* controller where controller
    # output is opposite sign of error(kp and ki < 0)

    lb: int256 = self.output_lower_bound
    ub: int256 = self.output_upper_bound

    if (
        (bounded_pi_output == lb and new_area > 0  and error_integral > 0)
        or
        (bounded_pi_output == ub and new_area < 0  and error_integral < 0)
    ):
        return new_error_integral - new_area

    # default: no clamp
    return new_error_integral

@internal
@view
def _get_new_error_integral(scid: uint72, error: int256) -> (int256, int256):
    return (self.error_integral[scid] + error, error)

@external
@view
def get_new_error_integral(scid: uint72, error: int256) -> (int256, int256):
    return self._get_new_error_integral(scid, error)

@internal
@view
def _get_raw_pi_output(error: int256, errorI: int256) -> int256:
    # output = P + I = Kp * error + Ki * errorI
    control_output: ControlOutput = self.control_output
    p_output: int256 = (error * convert(control_output.kp, int256)) // EIGHTEEN_DECIMAL_NUMBER
    i_output: int256 = (errorI * convert(control_output.ki, int256)) // EIGHTEEN_DECIMAL_NUMBER

    return convert(control_output.co_bias, int256) + p_output + i_output

@external
@view
def get_raw_pi_output(error: int256, errorI: int256) -> int256:
    return self._get_raw_pi_output(error, errorI)

@external
@pure
def error(target: int256, measured: int256) -> int256:
    return self._error(target, measured)

@internal
@pure
def _error(target: int256, measured: int256) -> int256:
     return (target - measured) * EIGHTEEN_DECIMAL_NUMBER // target

@external
@view
def calc_deviation(scid: uint72, value_diff: uint256) -> uint256:
    return self._calc_deviation(scid, value_diff)

@internal
@view
def _calc_deviation(scid: uint72, value_diff: uint256) -> uint256:
    # calculates how many scales the new_value has deviated from current_value
    target_scale: uint256 = self.scales[scid]
    assert target_scale != 0, "unknown scid"

    return value_diff*EIGHTEEN_DECIMAL_NUMBER_U//target_scale

@internal
def _calc_reward_mult(scid: uint72, time_since: uint256) -> int256:
    count: uint32 = self.count[scid]
    min_window_size: uint32 = self.min_window_size

    # update oracle update_interval
    interval_ema: uint256 = self._update_interval_ema(scid, time_since)

    # Dont use feedback if number of samples is lt window size
    if count + 1 < min_window_size:
        self.count[scid] = count + 1
        return EIGHTEEN_DECIMAL_NUMBER

    update_interval: int256 = convert(interval_ema, int256)
    error: int256 = self._error(convert(self.target_time_since, int256), update_interval)

    reward_mult: int256 = 0
    #p_output: int256 = 0
    #i_output: int256 = 0

    # update feedback mechanism and get current reward multiplier
    #reward_mult, p_output, i_output = self._update(scid, error)[0]
    reward_mult = self._update_feedback(scid, error)

    self.count[scid] = count + 1

    return reward_mult

@internal
def _add_updater(updater: address):
    n:  uint32 = self.n_updaters
    if not self.has_updated[updater]:
        self.updaters[n] = updater
        self.n_updaters = n + 1
        self.has_updated[updater] = True

@external
@view
def get_updaters_chunk(start: uint256, count: uint256) -> DynArray[TotalRewards, 256]:
    assert count <= 256
    total_rewards: DynArray[TotalRewards, 256] = []
    updater_rewards: TotalRewards = empty(TotalRewards)

    for i: uint256 in range(count, bound=256):
        idx: uint256 = start + i
        updater: address = self.updaters[idx]
        if updater == empty(address):
            break
        total_rewards.append(TotalRewards(address=updater, total_rewards=self.rewards[updater]))

    return total_rewards

@external
@payable
def update_many(dat: Bytes[MAX_PAYLOAD_SIZE]) -> DynArray[EnhancedReward, MAX_PAYLOADS]:
    assert not self.frozen, "Rewards contract is frozen"

    receipts: DynArray[RecordReceipt, MAX_PAYLOADS] = extcall self.oracle.storeValuesWithReceipt(dat, value=msg.value)
    rewards: DynArray[EnhancedReward, MAX_PAYLOADS] = []

    tip_reward_type: uint16 = self.tip_reward_type
    coeff: Coefficients = self.coeff
    old_tip_val: uint240 = 0
    old_bf_val: uint240 = 0
    new_tip_val: uint240 = 0
    new_bf_val: uint240 = 0

    tip_system_id: uint8 = 0
    tip_chain_id: uint64 = 0
    bf_system_id: uint8 = 0
    bf_chain_id: uint64 = 0

    bf_found: bool = False
    tip_found: bool = False

    old_gasprice: uint240 = 0
    new_gasprice: uint240 = 0
    deviation: uint256 = 0
    time_since: uint256 = 0
    time_reward: int256 = 0
    deviation_reward: int256 = 0
    reward_mult: int256 = 0
    time_reward_adj: int256 = 0
    deviation_reward_adj: int256 = 0
    time_reward_adj_u: uint256 = 0
    deviation_reward_adj_u: uint256 = 0
    scid: uint72 = 0

    self._add_updater(msg.sender)

    for rec: RecordReceipt in receipts:
        sid: uint8 = rec.systemid
        cid: uint64 = rec.cid

        if rec.typ == tip_reward_type:
            old_tip_val = rec.old_value
            new_tip_val = rec.new_value
            tip_system_id = sid
            tip_chain_id = cid
            tip_found = True
        elif rec.typ == BASEFEE_REWARD_TYPE:
            old_bf_val = rec.old_value
            new_bf_val = rec.new_value
            bf_system_id = sid
            bf_chain_id = cid
            bf_found = True
        else:
            continue

        # tip and bf found for this cid, time to process
        if not (tip_found and bf_found):
            continue

        assert tip_system_id == bf_system_id, "System IDs for tip and basefee types don't match. Out of order data?"
        assert tip_chain_id == bf_chain_id, "Chain IDs for tip and basefee types don't match. Out of order data?"

        # reset these
        tip_found = False
        bf_found = False

        old_gasprice = old_tip_val + old_bf_val
      
        # zero new_height means this type was not updated, so no reward
        if (rec.new_height == 0):
            rewards.append(EnhancedReward(system_id=sid,
                                          chain_id=cid,
                                          height=rec.old_height,
                                          gas_price=old_gasprice,
                                          time_reward=0,
                                          deviation_reward=0))
            continue


        new_gasprice = new_tip_val + new_bf_val

        scid = convert(shift(convert(rec.cid, uint256), 8) | convert(sid, uint256), uint72)

        # raw deviation is used in event
        raw_deviation: uint240 = 0
        if new_gasprice > old_gasprice:
            raw_deviation = new_gasprice - old_gasprice
        else:
            raw_deviation = old_gasprice - new_gasprice

        # deviation and time_since are used to calculate rewards
        deviation = self._calc_deviation(scid, convert(raw_deviation, uint256))
        time_since = convert(rec.new_timestamp - rec.old_timestamp, uint256) * EIGHTEEN_DECIMAL_NUMBER_U

        # Dont reward
        if not self.rewards_enabled:
            log OracleUpdated(updater=msg.sender, system_id=sid, chain_id=cid,
                              new_value=new_gasprice, raw_deviation=raw_deviation,
                              time_since=convert(time_since//10**21, uint48),
                              time_reward=0, deviation_reward=0,
                              reward_mult=0)

            rewards.append(EnhancedReward(system_id=sid,
                                          chain_id=cid,
                                          height=rec.old_height,
                                          gas_price=old_gasprice,
                                          time_reward=0,
                                          deviation_reward=0))
            continue
        else:

            # calculate reward
            time_reward, deviation_reward = self._calc_reward(convert(time_since, int256)//1000,
                                                              convert(deviation, int256),
                                                              coeff)
         
            # calculate reward multiplier
            reward_mult = self._calc_reward_mult(scid, time_since//1000)

            # adjust rewards with multiplier
            time_reward_adj = reward_mult * time_reward // EIGHTEEN_DECIMAL_NUMBER
            deviation_reward_adj = reward_mult * deviation_reward // EIGHTEEN_DECIMAL_NUMBER

            time_reward_adj_u = convert(time_reward_adj, uint256)
            deviation_reward_adj_u = convert(deviation_reward_adj, uint256)

            # store rewards
            self.rewards[msg.sender] += time_reward_adj_u + deviation_reward_adj_u
            self.total_rewards += time_reward_adj_u + deviation_reward_adj_u

            log OracleUpdated(updater=msg.sender, system_id=sid, chain_id=cid,
                              new_value=new_gasprice, raw_deviation=raw_deviation,
                              time_since=convert(time_since//10**21, uint48),
                              time_reward=time_reward_adj_u, deviation_reward=deviation_reward_adj_u,
                              reward_mult=reward_mult)

            rewards.append(EnhancedReward(system_id=sid,
                                          chain_id=cid,
                                          height=rec.old_height,
                                          gas_price=old_gasprice,
                                          time_reward=time_reward_adj_u,
                                          deviation_reward=deviation_reward_adj_u))

    return rewards

@external
@view
def calc_reward(time_since: int256, deviation: int256) -> (int256, int256):
    coeff: Coefficients = self.coeff
    return self._calc_reward(time_since, deviation, coeff)

@external
@view
def calc_time_reward(time_since: int256) -> int256:
    coeff: Coefficients = self.coeff
    return self._calc_time_reward(time_since, coeff)

@internal
@view
def _calc_time_reward(time_since: int256, coeff: Coefficients) -> int256:
    return max(min(convert(coeff.zero, int256)*time_since//EIGHTEEN_DECIMAL_NUMBER + 
           convert(coeff.two, int256)*time_since*time_since//THIRTY_SIX_DECIMAL_NUMBER, self.max_time_reward), self.min_time_reward)

@external
@view
def calc_deviation_reward(time_since: int256) -> int256:
    coeff: Coefficients = self.coeff
    return self._calc_deviation_reward(time_since, coeff)

@internal
@view
def _calc_deviation_reward(deviation: int256, coeff: Coefficients) -> int256:
    return max(min(convert(coeff.one, int256)*deviation//EIGHTEEN_DECIMAL_NUMBER +
           convert(coeff.three, int256)*deviation*deviation//THIRTY_SIX_DECIMAL_NUMBER, self.max_deviation_reward), self.min_deviation_reward)

@internal
@view
def _calc_reward(time_since: int256, deviation: int256, coeff: Coefficients) -> (int256, int256):
    return self._calc_time_reward(time_since, coeff), self._calc_deviation_reward(deviation, coeff)

@external
def test_update_interval_ema(scid: uint72, new_value: uint256) -> uint256:
    return self._update_interval_ema(scid, new_value)

@internal
def _update_interval_ema(scid: uint72, new_value: uint256) -> uint256:
    current_ema: uint256 = self.interval_ema[scid]
    new_ema: uint256 = (ALPHA_COMP * new_value + EMA_ALPHA * current_ema)//EIGHTEEN_DECIMAL_NUMBER_U
    self.interval_ema[scid] = new_ema
    return new_ema

@external
def test_update_feedback(scid: uint72, error: int256) -> int256:
    return self._update_feedback(scid, error)

@internal
def _update_feedback(scid: uint72, error: int256) -> int256:
    # update feedback mechanism
    error_integral: int256 = self.error_integral[scid]
    new_error_integral: int256 = error_integral + error

    pi_output: int256 = 0
    pi_output = self._get_raw_pi_output(error, new_error_integral)

    bounded_pi_output: int256 = self._bound_pi_output(pi_output)

    self.error_integral[scid] = self._clamp_error_integral(bounded_pi_output, error_integral, new_error_integral, error)

    self.last_output[scid] = bounded_pi_output

    return bounded_pi_output

@external
@view
def get_new_pi_output(scid: uint72, error: int256) -> int256:
    return self._get_new_pi_output(scid, error)

@internal
@view
def _get_new_pi_output(scid:  uint72, error: int256) -> int256:
    new_error_integral: int256 = 0
    tmp: int256 = 0
    (new_error_integral, tmp) = self._get_new_error_integral(scid, error)

    pi_output: int256 = 0
    pi_output = self._get_raw_pi_output(error, new_error_integral)

    bounded_pi_output: int256 = self._bound_pi_output(pi_output)

    return bounded_pi_output
