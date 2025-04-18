#pragma version 0.4.1
#pragma optimize none

interface IOracle:
    def get(systemid: uint8, cid: uint64, typ: uint16) -> (uint256, uint64, uint48): view
    def storeValues(dat: Bytes[16384]): nonpayable
    def storeValuesWithReceipt(dat: Bytes[16384]) -> DynArray[RecordReceipt, MAX_PAYLOADS]: nonpayable

event OracleUpdated:
    updater: address
    chain_id: uint64
    new_value: uint240
    deviation: uint256
    time_since: uint256
    time_reward: uint256
    deviation_reward: uint256
    reward_mult: int256

struct Scale:
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

struct Reward:
    time_reward: uint256
    deviation_reward: uint256

struct EnhancedReward:
    chain_id: uint64
    height: uint64
    gas_price: uint240
    time_reward: uint256
    deviation_reward: uint256

struct TotalRewards:
    updater: address
    total_rewards: uint256

BASEFEE_REWARD_TYPE: public(constant(uint16)) = 107
MAX_PAYLOADS: public(constant(uint256)) = 32
MAX_UPDATERS: public(constant(uint32)) = 2**16
MAX_PAYLOAD_SIZE: public(constant(uint256)) = 16384

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
default_window_size: public(uint256)
window_size: HashMap[uint64, uint256]
has_updated: public(HashMap[address, bool])
updaters: public(address[MAX_UPDATERS])
n_updaters:  public(uint32)
frozen: public(bool)
oracle: public(IOracle)

error_integral: public(HashMap[uint64, int256])
last_output: public(HashMap[uint64, int256])

rewards: public(HashMap[address, uint256])
total_rewards: public(uint256)
scales: public(HashMap[uint64, uint256])

oracle_values: HashMap[uint64, HashMap[uint256, uint256]]  # Circular buffer simulated via mapping
index: HashMap[uint64, uint256]  # Pointer to next insert position (0 to N-1)
count: HashMap[uint64, uint256]  # Number of elements inserted so far, up to N
rolling_sum: HashMap[uint64, uint256]  # Sum of last N values for efficient averaging

coeff: public(Coefficients)
intercept: public(int256)

EIGHTEEN_DECIMAL_NUMBER: constant(int256) = 10**18
THIRTY_SIX_DECIMAL_NUMBER: constant(int256) = 10**36
EIGHTEEN_DECIMAL_NUMBER_U: constant(uint256) = 10**18

@deploy
def __init__(_kp: int80, _ki: int80, _co_bias: int80,
             _output_upper_bound: int256, _output_lower_bound: int256, _target_time_since: uint256,
             _tip_reward_type: uint16,
             _min_reward: uint256, _max_reward: uint256,
             _default_window_size: uint256, oracle: address,
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
    self.default_window_size = _default_window_size
    self.oracle = IOracle(oracle)
    self.coeff = Coefficients(zero=_coeff[0], one=_coeff[1], two=_coeff[2], three=_coeff[3])

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
    for s: Scale in scales:
        self.scales[s.chain_id] = s.scale

@external
def set_scale(chain_id: uint64, scale: uint256):
    assert self.authorities[msg.sender]
    self.scales[chain_id] = scale

@external
def freeze():
    assert self.authorities[msg.sender]
    self.frozen = True

@external
def unfreeze():
    assert self.authorities[msg.sender]
    self.frozen = False

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
    elif (parameter == "default_window_size"):
        self.default_window_size = val
    else:
        raise "RewardController/modify-unrecognized-param"

@external
@pure
def test_decode_head(dat: Bytes[MAX_PAYLOAD_SIZE]) -> (uint8, uint64, uint16, uint48, uint64):
    return self._decode_head(dat)

@internal
@pure
def _decode_head(dat: Bytes[MAX_PAYLOAD_SIZE]) -> (uint8, uint64, uint16, uint48, uint64):
    h: uint64 = convert(slice(dat, 23, 8), uint64)  # Extract last 8 bytes of 32-byte block, excluding version
    cid: uint64 = convert(slice(dat, 15, 8), uint64)
    sid: uint8 = convert(slice(dat, 14, 1), uint8)
    plen: uint16 = convert(slice(dat, 6, 2), uint16)
    ts: uint48 = convert(slice(dat, 8, 6), uint48)  # Extract 6 bytes before sid

    return sid, cid, plen, ts, h

@internal
@pure
def _decode_plen(dat: Bytes[MAX_PAYLOAD_SIZE]) -> uint16:
    plen: uint16 = convert(slice(dat, 6, 2), uint16)
    return plen

@external
@pure
def decode(dat: Bytes[MAX_PAYLOAD_SIZE], tip_typ: uint16) -> (uint8, uint64, uint240, uint240, uint48, uint64):
    return self._decode(dat, tip_typ)

@internal
@pure
def _decode(dat: Bytes[MAX_PAYLOAD_SIZE], tip_typ: uint16) -> (uint8, uint64, uint240, uint240, uint48, uint64):
    sid: uint8 = 0 
    cid: uint64 = 0 
    plen: uint16 = 0 
    ts: uint48 = 0 
    h: uint64 = 0 

    sid, cid, plen, ts, h = self._decode_head(dat)
    plen_int: uint256 = convert(plen, uint256)

    typ: uint16 = 0 
    val: uint240 = 0 
    basefee_val: uint240 = 0 
    tip_val: uint240 = 0 
    
    for j: uint256 in range(plen_int, bound=256):
        val_b: Bytes[32] = slice(dat, 32 + j*32, 32)  
        typ = convert(slice(val_b, 0, 2), uint16)
        val = convert(slice(val_b, 2, 30), uint240)

        if typ == BASEFEE_REWARD_TYPE:
            basefee_val = val
        elif typ == tip_typ:
            tip_val = val

        # if both have been set, stop parsing
        if basefee_val != 0 and tip_val !=0:
            break

    return sid, cid, basefee_val, tip_val, ts, h

@internal
@view
def _riemann_sum(x: int256, y: int256)-> int256:
    return (x + y) // 2

@internal
@view
def _bound_pi_output(pi_output: int256) -> int256:
    bounded_pi_output: int256 = pi_output
    if pi_output < self.output_lower_bound:
        bounded_pi_output = self.output_lower_bound
    elif pi_output > self.output_upper_bound:
        bounded_pi_output = self.output_upper_bound

    return bounded_pi_output

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
def _clamp_error_integral(bounded_pi_output:int256, error_integral: int256, new_error_integral: int256, new_area: int256) -> int256: 
    # This logic is strictly for a *reverse-acting* controller where controller
    # output is opposite sign of error(kp and ki < 0)
    clamped_error_integral: int256 = new_error_integral
    if (bounded_pi_output == self.output_lower_bound and new_area > 0 and error_integral > 0):
        clamped_error_integral = clamped_error_integral - new_area
    elif (bounded_pi_output == self.output_upper_bound and new_area < 0 and error_integral < 0):
        clamped_error_integral = clamped_error_integral - new_area
    return clamped_error_integral

@internal
@view
def _get_new_error_integral(cid: uint64, error: int256) -> (int256, int256):
    return (self.error_integral[cid] + error, error)

@external
@view
def get_new_error_integral(cid: uint64, error: int256) -> (int256, int256):
    return self._get_new_error_integral(cid, error)

@internal
@view
def _get_raw_pi_output(error: int256, errorI: int256) -> (int256, int256, int256):
    # // output = P + I = Kp * error + Ki * errorI
    control_output: ControlOutput = self.control_output
    p_output: int256 = (error * convert(control_output.kp, int256)) // EIGHTEEN_DECIMAL_NUMBER
    i_output: int256 = (errorI * convert(control_output.ki, int256)) // EIGHTEEN_DECIMAL_NUMBER

    return (convert(control_output.co_bias, int256) + p_output + i_output, p_output, i_output)

@external
@view
def get_raw_pi_output(error: int256, errorI: int256) -> (int256, int256, int256):
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
def calc_deviation(cid: uint64, new_value: uint256, current_value: uint256) -> uint256:
    return self._calc_deviation(cid, new_value, current_value)

@internal
@view
def _calc_deviation(cid: uint64, new_value: uint256, current_value: uint256) -> uint256:
    target_scale: uint256 = self.scales[cid]
    assert target_scale != 0, "scale for cid is zero"

    if new_value > current_value:
        return (new_value - current_value)*EIGHTEEN_DECIMAL_NUMBER_U//target_scale
    else:
        return (current_value - new_value)*EIGHTEEN_DECIMAL_NUMBER_U//target_scale

@internal
def _calc_reward_mult(cid: uint64, time_since: uint256) -> int256:
    count: uint256 = self.count[cid]
    window_size: uint256 = self._get_window_size(cid)

    # update oracle update_interval
    self._add_value(cid, time_since, count, window_size)

    # Dont use feedback if number of samples is lt window size
    if count + 1 < window_size:
        return EIGHTEEN_DECIMAL_NUMBER

    update_interval: int256 = convert(self._get_average(cid), int256)
    error: int256 = self._error(convert(self.target_time_since, int256), update_interval)

    reward_mult: int256 = 0
    p_output: int256 = 0
    i_output: int256 = 0

    # update feedback mechanism and get current reward multiplier
    reward_mult, p_output, i_output = self._update(cid, error)

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
def get_updaters_chunk(start: uint256, count: uint256) -> (address[256], uint256[256]):
    assert count <= 256
    result_updaters: address[256] = empty(address[256])
    result_rewards: uint256[256] = empty(uint256[256])

    for i: uint256 in range(count, bound=256):
        idx: uint256 = start + i
        updater: address = self.updaters[idx]
        result_updaters[i] = updater
        result_rewards[i] = self.rewards[updater]

    return result_updaters, result_rewards

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

@external
def update_many(dat: Bytes[MAX_PAYLOAD_SIZE])-> EnhancedReward[MAX_PAYLOADS]:
    receipts: DynArray[RecordReceipt, MAX_PAYLOADS] = extcall self.oracle.storeValuesWithReceipt(dat)
    rewards: EnhancedReward[MAX_PAYLOADS] = empty(EnhancedReward[MAX_PAYLOADS])
    cid: uint64 = 0
    typ: uint16 = 0
    rec: RecordReceipt = empty(RecordReceipt)
    old_tip_val: uint240 = 0
    old_bf_val: uint240 = 0
    new_tip_val: uint240 = 0
    new_bf_val: uint240 = 0

    bf_found: bool = False
    tip_found: bool = False

    current_gasprice: uint240 = 0
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

    # self.tip_reward_type
    # BASEFEE_REWARD_TYPE
    idx: uint256 = 0
    for i: uint256 in range(len(receipts), bound=MAX_PAYLOADS):
        rec = receipts[i]

        if rec.typ == self.tip_reward_type:
            old_tip_val = rec.old_value
            new_tip_val = rec.new_value
            tip_found = True
        elif rec.typ == BASEFEE_REWARD_TYPE:
            old_bf_val = rec.old_value
            new_bf_val = rec.new_value
            bf_found = True

        # tip and bf found for this cid, time to process
        if not (tip_found and bf_found):
            continue

        # reset these
        tip_found = False
        bf_found = False

        current_gasprice = old_tip_val + old_bf_val
      
        # no update
        if rec.old_timestamp == rec.new_timestamp:
            rewards[idx] = EnhancedReward(chain_id=rec.cid,
                                        height=rec.old_height,
                                        gas_price=current_gasprice,
                                        time_reward=0,
                                        deviation_reward=0)
            continue

        new_gasprice = new_tip_val + new_bf_val

        # calculate deviation and staleness(time_since) for new values
        deviation = self._calc_deviation(rec.cid, convert(new_gasprice, uint256), convert(current_gasprice, uint256))

        time_since = convert(rec.new_timestamp - rec.old_timestamp, uint256) * EIGHTEEN_DECIMAL_NUMBER_U

        # calculate reward
        time_reward, deviation_reward = self._calc_reward(convert(time_since, int256)//1000, convert(deviation, int256))
     
        # calculate reward multiplier
        reward_mult = self._calc_reward_mult(rec.cid, time_since//1000)

        # adjust rewards with multiplier
        time_reward_adj = reward_mult * time_reward // EIGHTEEN_DECIMAL_NUMBER
        deviation_reward_adj = reward_mult * deviation_reward // EIGHTEEN_DECIMAL_NUMBER

        time_reward_adj_u = convert(time_reward_adj, uint256)
        deviation_reward_adj_u = convert(deviation_reward_adj, uint256)

        # store rewards
        self.rewards[msg.sender] += time_reward_adj_u + deviation_reward_adj_u
        self.total_rewards += time_reward_adj_u + deviation_reward_adj_u

        log OracleUpdated(updater=msg.sender, chain_id=rec.cid, new_value=new_gasprice,
                          deviation=deviation, time_since=time_since,
                          time_reward=time_reward_adj_u, deviation_reward=deviation_reward_adj_u,
                          reward_mult=reward_mult)

        rewards[idx] = EnhancedReward(chain_id=rec.cid,
                                    height=rec.old_height,
                                    gas_price=current_gasprice,
                                    time_reward=time_reward_adj_u,
                                    deviation_reward=deviation_reward_adj_u)
        idx += 1

    return rewards

@internal
def _update_oracle_stub(dat: Bytes[MAX_PAYLOAD_SIZE], l: uint256)-> (uint256, uint256):
    tip_typ: uint16 = self.tip_reward_type
    return 0, 0

@external
@view
def calc_reward(time_since: int256, deviation: int256) -> (int256, int256):
    return self._calc_reward(time_since, deviation)

@external
@view
def calc_time_reward(time_since: int256) -> int256:
    return self._calc_time_reward(time_since)

@internal
@view
def _calc_time_reward(time_since: int256) -> int256:
    coeff: Coefficients = self.coeff
    return max(min(convert(coeff.zero, int256)*time_since//EIGHTEEN_DECIMAL_NUMBER + 
           convert(coeff.two, int256)*time_since*time_since//THIRTY_SIX_DECIMAL_NUMBER, self.max_time_reward), self.min_time_reward)

@external
@view
def calc_deviation_reward(time_since: int256) -> int256:
    return self._calc_deviation_reward(time_since)

@internal
@view
def _calc_deviation_reward(deviation: int256) -> int256:
    coeff: Coefficients = self.coeff
    return max(min(convert(coeff.one, int256)*deviation//EIGHTEEN_DECIMAL_NUMBER +
           convert(coeff.three, int256)*deviation*deviation//THIRTY_SIX_DECIMAL_NUMBER, self.max_deviation_reward), self.min_deviation_reward)

@internal
@view
def _calc_reward(time_since: int256, deviation: int256) -> (int256, int256):
    return self._calc_time_reward(time_since), self._calc_deviation_reward(deviation)

@external
def test_add_value(chain_id: uint64, new_value: uint256):
    count: uint256 = self.count[chain_id]
    window_size: uint256 = self._get_window_size(chain_id)
    self._add_value(chain_id, new_value, count, window_size)

@external
@view
def get_window_size(chain_id: uint64) -> uint256:
    return self._get_window_size(chain_id)

@internal
@view
def _get_window_size(chain_id: uint64) -> uint256:
    value: uint256 = self.window_size[chain_id]
    if value == 0:
        return self.default_window_size
    return value

@internal
def _add_value(chain_id: uint64, new_value: uint256, count: uint256, window_size: uint256):
    #Add a new value to the circular buffer and update rolling sum.

    old_value: uint256 = 0

    if count < window_size:
        # Buffer not full yet
        self.count[chain_id] += 1
    else:
        # Buffer full: value at index will be overwritten
        old_value = self.oracle_values[chain_id][self.index[chain_id]]

    # Update rolling sum
    self.rolling_sum[chain_id] = self.rolling_sum[chain_id] + new_value - old_value

    # Store new value in buffer
    self.oracle_values[chain_id][self.index[chain_id]] = new_value

    # Update index (circular increment)
    self.index[chain_id] = (self.index[chain_id] + 1) % window_size

@external
@view
def get_average(chain_id: uint64) -> uint256:
    return self._get_average(chain_id)

@internal
@view
def _get_average(chain_id: uint64) -> uint256:
    if self.count[chain_id] == 0:
        return 0  # Avoid division by zero if no values added yet
    return self.rolling_sum[chain_id] // self.count[chain_id]

@external
def resize_buffer(chain_id: uint64, new_window_size: uint256):
    assert self.authorities[msg.sender]
    # Resize the buffer to a new window_size and adjust sum/count as needed.
    assert new_window_size > 0, "New window_size must be greater than 0"

    if new_window_size == self._get_window_size(chain_id):
        return  # No change needed

    # CASE 1: Increasing window_size — simple adjustment
    if new_window_size > self.count[chain_id]:
        self.window_size[chain_id] = new_window_size
        return

    # CASE 2: Decreasing window_size — need to keep last `new_window_size` items
    # Step 1: Identify starting point for last `new_window_size` items
    items_to_keep: uint256 = new_window_size
    start: uint256 = (self.index[chain_id] + (self.count[chain_id] - items_to_keep)) % self.count[chain_id]

    # Step 2: Rebuild buffer from these items
    temp_sum: uint256 = 0

    for i: uint256 in range(items_to_keep, bound=100000):
        pos: uint256 = (start + i) % self.count[chain_id]
        value: uint256 = self.oracle_values[chain_id][pos]  # Value to keep
        self.oracle_values[chain_id][i] = value  # Move to new position
        temp_sum += value

    # Step 3: Update state variables
    self.window_size[chain_id] = new_window_size
    self.count[chain_id] = items_to_keep
    self.rolling_sum[chain_id] = temp_sum
    self.index[chain_id] = items_to_keep % new_window_size  # Where next value will go

    # NOTE: Old values beyond `new_window_size` will remain in storage, but ignored logically.

@external
def test_update(cid: uint64, error: int256) -> (int256, int256, int256):
    return self._update(cid, error)

@internal
def _update(cid: uint64, error: int256) -> (int256, int256, int256):
    # update feedback mechanism
    error_integral: int256 = self.error_integral[cid]
    new_error_integral: int256 = error_integral + error

    pi_output: int256 = 0
    p_output: int256 = 0
    i_output: int256 = 0
    (pi_output, p_output, i_output) = self._get_raw_pi_output(error, new_error_integral)

    bounded_pi_output: int256 = self._bound_pi_output(pi_output)

    self.error_integral[cid] = self._clamp_error_integral(bounded_pi_output, error_integral, new_error_integral, error)

    self.last_output[cid] = bounded_pi_output

    return (bounded_pi_output, p_output, i_output)

@external
@view
def get_new_pi_output(cid: uint64, error: int256) -> (int256, int256, int256):
    return self._get_new_pi_output(cid, error)

@internal
@view
def _get_new_pi_output(cid:  uint64, error: int256) -> (int256, int256, int256):
    new_error_integral: int256 = 0
    tmp: int256 = 0
    (new_error_integral, tmp) = self._get_new_error_integral(cid, error)

    pi_output: int256 = 0
    p_output: int256 = 0
    i_output: int256 = 0
    (pi_output, p_output, i_output) = self._get_raw_pi_output(error, new_error_integral)

    bounded_pi_output: int256 = self._bound_pi_output(pi_output)

    return (bounded_pi_output, p_output, i_output)
