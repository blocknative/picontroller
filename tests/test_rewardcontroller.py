import os
import random
import json
import time
import ape
import pytest
import numpy as np
from web3 import Web3, HTTPProvider
import matplotlib.pyplot as plt

web3 = Web3()
from ape import accounts
from ape import Contract

import params
from addresses import oracle_addresses, gasnet_contract

from fixture import owner, oracle, controller
from fixture import oracle
import utils

TWENTY_SEVEN_DECIMAL_NUMBER = int(10 ** 27)
EIGHTEEN_DECIMAL_NUMBER     = int(10 ** 18)

DELIMITER = b'0000000000000000000000000000000'

update_delay = 3600;

# Use this to match existing controller tests
def assertEq(x, y):
    assert x == y

def assertGt(x, y):
    assert x > y

def assertLt(x, y):
    assert x < y

def relative_error(measured_value, reference_value):
    # measured_value is WAD, reference_value is a RAY
    assert isinstance(measured_value, int)
    assert isinstance(reference_value, int)

    scaled_measured_value = measured_value *  int(10**9)
    return ((reference_value - scaled_measured_value) * TWENTY_SEVEN_DECIMAL_NUMBER) // reference_value

class TestRewardController:
    def check_state(self, owner, controller):
        assert controller.authorities(owner) == 1
        assert controller.output_upper_bound() == params.output_upper_bound
        assert controller.output_lower_bound() == params.output_lower_bound
        assert controller.error_integral(1) == 0
        assert controller.control_output().kp == params.kp
        assert controller.control_output().ki == params.ki

    def test_contract_fixture(self, owner, controller):
        assertEq(controller.authorities(owner), 1);
        assertEq(controller.output_upper_bound(), params.output_upper_bound);
        assertEq(controller.output_lower_bound(), params.output_lower_bound);
        assertEq(controller.error_integral(1), 0);
        assertEq(params.kp, controller.control_output().kp);
        assertEq(params.ki, controller.control_output().ki);

    def test_modify_parameters(self, owner, controller):
        controller.modify_parameters_control_output("kp", int(1), sender=owner);
        controller.modify_parameters_control_output("ki", int(2), sender=owner);
        controller.modify_parameters_control_output("co_bias", int(3), sender=owner);
        assert int(1) == controller.control_output().kp
        assert int(2) == controller.control_output().ki
        assert int(3) == controller.control_output().co_bias

        controller.modify_parameters_int("output_upper_bound", int(TWENTY_SEVEN_DECIMAL_NUMBER + 1), sender=owner);
        controller.modify_parameters_int("output_lower_bound", -int(1), sender=owner);
        assert controller.output_upper_bound() == int(TWENTY_SEVEN_DECIMAL_NUMBER + 1)
        assert controller.output_lower_bound() == -int(1)

        controller.modify_parameters_uint("target_time_since", 600, sender=owner);
        controller.modify_parameters_uint("min_reward", 100, sender=owner);
        controller.modify_parameters_uint("max_reward", 1000, sender=owner);

        assert controller.target_time_since() ==  600
        assert controller.min_reward() ==  100
        assert controller.max_reward() ==  1000

    def test_fail_modify_parameters_control_upper_bound(self, owner, controller):
        #with ape.reverts("RewardController/invalid-output_upper_bound"):
        with ape.reverts():
            controller.modify_parameters_int("output_upper_bound", controller.output_lower_bound() - 1, sender=owner);
    
    def test_fail_modify_parameters_control_lower_bound(self, owner, controller):
        with ape.reverts():
            controller.modify_parameters_int("output_lower_bound", controller.output_upper_bound() + 1, sender=owner);

    def test_get_next_output_zero_error(self, owner, controller):
        pi_output = controller.get_new_pi_output(1,0);
        assert pi_output == params.co_bias + 0
        assert controller.error_integral(1) == 0

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_next_output_nonzero_error(self, owner, controller):
        error = relative_error(int(1.1E18), 10**27);
        assert error == -100000000000000000000000000

        pi_output = controller.get_new_pi_output(1,error);
        assert pi_output != 0
        assert controller.error_integral(1) == 0
        assert pi_output == min(params.co_bias + params.kp * int(error/10**18) + params.ki * int(error/10**18), params.output_upper_bound)

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_zero_error(self, owner, controller):
        error = relative_error(EIGHTEEN_DECIMAL_NUMBER, TWENTY_SEVEN_DECIMAL_NUMBER);
        pi_output = controller.get_raw_pi_output(error, 0);
        assertEq(pi_output, params.co_bias + 0);
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_nonzero_error(self, owner, controller):
        error = int(10**20)
        pi_output = controller.get_raw_pi_output(error, 0);
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_small_nonzero_error(self, owner, controller):
        error = int(10**18)
        pi_output = controller.get_raw_pi_output(error, 0);
        assert pi_output < 0
        assert controller.error_integral(1) == 0

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_large_nonzero_error(self, owner, controller):
        error = int(10**20) * int(10**18)
        pi_output = controller.get_raw_pi_output(error, 0);
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_first_update(self, owner, controller, chain):
        next_ts = chain.pending_timestamp
        controller.test_update_feedback(1,1, sender=owner)
        # TODO use events
        #assert controller.last_update_time(1) == next_ts
        assert controller.error_integral(1) == 1
        assert controller.error_integral(100) == 0

    def test_first_update_zero_error(self, owner, controller, chain):
        next_ts = chain.pending_timestamp
        controller.test_update_feedback(1,0, sender=owner)
        # TODO use events
        #assertEq(controller.last_update_time(1), next_ts);
        assertEq(controller.error_integral(1), 0);

    def test_two_updates(self, owner, controller, chain):
        controller.test_update_feedback(1,1, sender=owner)
        controller.test_update_feedback(1,2, sender=owner)
        assert controller.error_integral(1) != 0
        assert controller.error_integral(100) == 0

    def test_first_get_next_output(self, owner, controller):
        bias = 3*10**18
        controller.modify_parameters_control_output("co_bias", bias, sender=owner);
        # positive error
        error = controller.error(1000*10**18, 999*10**18)
        assert error > 0
        pi_output = controller.get_new_pi_output(1,error);

        assert pi_output == params.kp * error//10**18  + params.ki * error//10**18 + controller.control_output().co_bias
        assert controller.error_integral(1) == 0

        # negative error
        error = controller.error(999*10**18, 1000*10**18)
        pi_output = controller.get_new_pi_output(1,error);
        assert pi_output == params.kp * error//10**18  + params.ki * error//10**18 + controller.control_output().co_bias
        assert controller.error_integral(1) == 0

    def test_first_negative_error(self, owner, controller, chain):
        error = controller.error(999*10**18, 1000*10**18)
        pi_output = controller.get_new_pi_output(1,error)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias

        next_ts = chain.pending_timestamp
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias

        # TODO use events
        #assert controller.last_update_time(1) == next_ts
        assert controller.error_integral(1) == error
        assert controller.error_integral(2) == 0

    def test_first_positive_error(self, owner, controller, chain):
        error = controller.error(1000*10**18, 999*10**18)
        pi_output = controller.get_new_pi_output(1,error)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias

        next_ts = chain.pending_timestamp
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias

        # TODO use events
        assert controller.error_integral(1) == error

    def test_basic_integral(self, owner, controller, chain):
        #controller.modify_parameters_int("kp", int(2.25*10**11), sender=owner);
        #controller.modify_parameters_int("ki", int(7.2 * 10**4), sender=owner);

        chain.pending_timestamp += update_delay

        error1 = controller.error(1000*10**18, 999*10**18)
        controller.test_update_feedback(1,error1, sender=owner);

        error_integral1 = controller.error_integral(1);
        assert error_integral1 == error1

        chain.pending_timestamp += update_delay

        # Second update
        error2 = controller.error(1001*10**18, 999*10**18)
        controller.test_update_feedback(1,error2, sender=owner);

        error_integral2 = controller.error_integral(1);

        assert error_integral2 == error_integral1 + error2
        return

        chain.pending_timestamp += update_delay

        # Third update
        error3 = controller.error(950*10**18, 999*10**18)
        controller.test_update_feedback(1,error3, sender=owner);
        error_integral3 = controller.error_integral(1);

        assert error_integral3, error_integral2 + error3
        
    def test_update_prate(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", int(2.25E11), sender=owner);
        controller.modify_parameters_control_output("ki", 0, sender=owner);
        chain.mine(3600, timestamp=chain.pending_timestamp+3600)

        error = relative_error(int(1.01E18), 10**27);
        assert error == -10 **25;
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        last_output = controller.last_output(1)
        assert last_output ==  controller.output_lower_bound()

    def test_get_next_error_integral(self, owner, controller, chain):
        update_delay = 3600
        chain.mine(update_delay//2, timestamp=chain.pending_timestamp+update_delay)

        error = controller.error(1000*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);

        assert new_integral == error
        assert new_area == error

        #update
        controller.test_update_feedback(1,error, sender=owner);
        assert controller.error_integral(1) == error

        chain.mine(update_delay//2)#, timestamp=chain.pending_timestamp+update_delay)
        next_pending_ts = chain.pending_timestamp + update_delay
        chain.pending_timestamp = next_pending_ts

        # Second update
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == error + error
        assert new_area == error
        #update
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #assert controller.last_update_time(1) == next_pending_ts
        assert controller.error_integral(1) == new_integral

        chain.pending_timestamp += update_delay

        # Third update
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == 3*error
        assert new_area == error
        controller.test_update_feedback(1,error, sender=owner);
        assert controller.error_integral(1)  == 3*error

    def test_last_error(self, owner, controller, chain):
        chain.pending_timestamp += update_delay

        error = relative_error(int(1.01E18), 10**27);
        assertEq(error, -10**25);
        controller.test_update_feedback(1,error, sender=owner);

        chain.pending_timestamp += update_delay

        error = relative_error(int(1.02E18), 10**27);
        assertEq(error, -10**25 * 2);
        controller.test_update_feedback(1,error, sender=owner);

    def test_lower_bound_limit(self, owner, controller, chain):
        chain.pending_timestamp += update_delay
        # create very large error
        huge_error = controller.error(1800*10**18, 1*10**18)
        pi_output = controller.get_new_pi_output(1,huge_error);

        assert pi_output == controller.output_lower_bound()

        controller.test_update_feedback(1,huge_error, sender=owner);
        # TODO use events

        assert pi_output == controller.output_lower_bound()

    def test_upper_bound_limit(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", int(100e18), sender=owner);
        error = relative_error(1, 10**27);
        pi_output = controller.get_new_pi_output(1, error);

        assert pi_output == controller.output_upper_bound()

        controller.test_update_feedback(1, error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)
        #assertEq(pi_output, controller.output_upper_bound());

    def test_raw_output_proportional_calculation(self, owner, controller, chain):
        error = controller.error(1000*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        pi_output = controller.get_raw_pi_output(error, 0);
        assert pi_output == params.kp * error//10**18 + controller.control_output().co_bias
        
        error = controller.error(960*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        pi_output = controller.get_raw_pi_output(error, 0);
        assert pi_output == params.kp * error//10**18 + controller.control_output().co_bias

    def test_both_gains_zero(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", 0, sender=owner);
        controller.modify_parameters_control_output("ki", 0, sender=owner);
        assertEq(controller.error_integral(1), 0);

        error = controller.error(1000*10**18, 999*10**18)

        pi_output = controller.get_new_pi_output(1,error);
        assert pi_output == 0 + controller.control_output().co_bias
        assert controller.error_integral(1) == 0

    def test_lower_clamping(self, owner, controller, chain):
        assert controller.control_output().kp < 0
        assert controller.control_output().ki < 0

        chain.pending_timestamp += update_delay

        error = controller.error(1800*10**18, 1750*10**18)
        assert error > 0

        # First error: small, output doesn't hit lower bound
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output, _, _) = controller.last_update(1)
        #assert pi_output < controller.control_output().co_bias
        #assert pi_output > controller.output_lower_bound();

        assert controller.error_integral(1) == error

        chain.pending_timestamp += update_delay

        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == error * 2
        assert new_area == error

        # Second error: small, output doesn't hit lower bound
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output2, _, _) = controller.last_update(1)
        #assert pi_output2 < pi_output;
        #assert pi_output2 > controller.output_lower_bound();
        assert controller.error_integral(1) == 2*error

        chain.pending_timestamp += update_delay

        # Third error: very large. Output hits lower bound
        # Integral *does not* accumulate
        huge_error = controller.error(1800*10**18, 1*10**18)
        assert error > 0

        (new_integral, new_area) = controller.get_new_error_integral(1, huge_error);
        assert new_area == huge_error
        assert new_integral == error * 2 + huge_error

        controller.test_update_feedback(1,huge_error, sender=owner);
        # TODO use events
        #(_, pi_output3, _, _) = controller.last_update(1)
        #assert pi_output3 == controller.output_lower_bound()

        # Integral doesn't accumulate
        clamped_integral = controller.error_integral(1)
        assert clamped_integral == 2* error

        chain.pending_timestamp += update_delay

        # Integral *does* accumulate with a smaller error(doesn't hit output bound)
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output4, _, _) = controller.last_update(1)
        assert controller.error_integral(1) > clamped_integral;
        #assert pi_output4 > controller.output_lower_bound();

    def test_upper_clamping(self, owner, controller, chain):
        assert controller.control_output().kp < 0
        assert controller.control_output().ki < 0

        chain.pending_timestamp += update_delay

        error = controller.error(1800*10**18, 1850*10**18)
        assert error < 0

        # First error: small, output doesn't hit upper bound
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output, _, _) = controller.last_update(1)
        #assert pi_output > controller.control_output().co_bias
        #assert pi_output < controller.output_upper_bound();

        assert controller.error_integral(1) == error

        chain.pending_timestamp += update_delay

        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == error * 2
        assert new_area == error

        # Second error: small, output doesn't hit lower bound
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output2, _, _) = controller.last_update(1)
        #assert pi_output2 > pi_output;
        #assert pi_output2 < controller.output_upper_bound();
        assert controller.error_integral(1) == 2*error

        chain.pending_timestamp += update_delay

        # Third error: very large. Output hits upper bound
        # Integral *does not* accumulate
        huge_error = controller.error(1800*10**18, 100000*10**18)
        assert error < 0

        # get_new_error_integral(1, 1) does not clamp
        (new_integral, new_area) = controller.get_new_error_integral(1, huge_error);
        assert new_area == huge_error
        assert new_integral == error * 2 + huge_error

        controller.test_update_feedback(1,huge_error, sender=owner);
        # TODO use events
        #(_, pi_output3, _, _) = controller.last_update(1)
        #assert pi_output3 == controller.output_upper_bound()

        # Integral doesn't accumulate
        clamped_integral = controller.error_integral(1)
        assert clamped_integral == 2* error

        chain.pending_timestamp += update_delay

        # Integral *does* accumulate with a smaller error(doesn't hit output bound)
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        #(_, pi_output4, _, _) = controller.last_update(1)
        #assert controller.error_integral(1) < clamped_integral;
        #assert pi_output4 < controller.output_upper_bound();

    def test_bounded_output_proportional_calculation(self, owner, controller, chain):
        # small error
        error = controller.error(1800*10**18, 1801*10**18)
        pi_output = controller.get_raw_pi_output(error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * error//10**18 + controller.control_output().co_bias
        assert bounded_output == pi_output

        # large negative error, hits upper bound
        huge_error = controller.error(1800*10**18, 100000*10**18)
        pi_output = controller.get_raw_pi_output(huge_error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * huge_error//10**18 + controller.control_output().co_bias
        assert bounded_output == controller.output_upper_bound()

        # large pos error, hits lower bound
        huge_error = controller.error(1000000*10**18, 1800*10**18)
        pi_output = controller.get_raw_pi_output(huge_error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * huge_error//10**18 + controller.control_output().co_bias
        assert bounded_output == controller.output_lower_bound()

    def test_last_error_integral(self, owner, controller, chain):

        chain.pending_timestamp += update_delay

        error = controller.error(1800*10**18, 1700*10**18)
        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        assert controller.error_integral(1) == error

        chain.pending_timestamp += update_delay

        controller.test_update_feedback(1,error, sender=owner);
        # TODO use events
        assert controller.error_integral(1) == error + error

        chain.pending_timestamp += update_delay
        assert controller.error_integral(1) == error + error

        controller.test_update_feedback(1,error, sender=owner);
        assert controller.error_integral(1) == error * 3

        chain.pending_timestamp += update_delay
        assert controller.error_integral(1) == error * 3

        controller.test_update_feedback(1,error, sender=owner);
        assert controller.error_integral(1) == error * 4
    # END CONTROL TESTING

    # START REWARD TESTING
    def test_set_scale(self, owner, controller, chain):
        controller.set_scale(2, 1, 3*10**15, sender=owner)
        assert controller.get_scale(2, 1) == 3*10**15

        controller.set_scale(2, 10, 10000, sender=owner)
        assert controller.get_scale(2, 10) == 10000

        controller.set_scale(2, 10, 20000, sender=owner)
        assert controller.get_scale(2, 10) == 20000
        assert controller.get_scale(2, 1) == 3*10**15

    def test_set_scales(self, owner, controller, chain):
        controller.set_scales([(2, 1, 3*10**15), (3, 10, 10000)], sender=owner)
        assert controller.get_scale(2, 1) == 3*10**15
        assert controller.get_scale(3, 10) == 10000

        controller.set_scales([(10, 1, 30*10**15), (20, 10, 10000)], sender=owner)
        assert controller.get_scale(10, 1) == 30*10**15
        assert controller.get_scale(20, 10) == 10000
        controller.set_scales([(1, 4, 40*10**15), (4, 11, 11000)], sender=owner)
        assert controller.get_scale(10, 1) == 30*10**15
        assert controller.get_scale(20, 10) == 10000
        assert controller.get_scale(1, 4) == 40*10**15
        assert controller.get_scale(4, 11) == 11000

    def test_time_reward(self, owner, controller, chain):
        assert controller.calc_time_reward(0) == controller.min_time_reward()
        assert controller.calc_time_reward(35*10**18) == controller.min_time_reward()
        assert controller.calc_time_reward(2740774000*10**18) == controller.max_time_reward()

    def test_calc_time_reward_min(self, owner, controller):
        assert controller.min_time_reward() == params.min_reward//2
        assert controller.calc_time_reward(0) - params.min_reward//2 == 0
        assert controller.calc_time_reward(params.min_ts) - params.min_reward//2 == 0

    def test_calc_time_reward_max(self, owner, controller):
        assert controller.max_time_reward() == params.max_reward//2
        assert controller.calc_time_reward(params.max_ts) - params.max_reward//2  < 10**15

    def test_deviation_reward(self, owner, controller, chain):
        assert controller.calc_deviation_reward(0) == controller.min_deviation_reward()
        assert controller.calc_time_reward(1000000000*10**18) == controller.max_deviation_reward()

    def test_calc_deviation_reward_min(self, owner, controller):
        assert controller.min_deviation_reward() == params.min_reward//2
        assert controller.calc_deviation_reward(0) - params.min_reward//2 == 0

    def test_calc_deviation_reward_max(self, owner, controller):
        assert controller.max_deviation_reward() == params.max_reward//2
        assert controller.calc_deviation_reward(params.max_deviation) - params.max_reward//2 < 10**15

    def test_calc_reward_min(self, owner, controller):
        assert abs(sum(controller.calc_reward(1, 0)) - params.min_reward) < 10**15

    def test_calc_reward_max(self, owner, controller):
        assert abs(sum(controller.calc_reward(params.max_ts, params.max_deviation)) - params.max_reward) < params.max_reward/100

    def test_calc_reward_half(self, owner, controller):
        assert abs(sum(controller.calc_reward(params.max_ts, params.min_deviation)) - params.max_reward//2) < params.max_reward/100
        assert abs(sum(controller.calc_reward(params.min_ts, params.max_deviation)) - params.max_reward//2) < params.max_reward/100

    def test_update_feedback(self, owner, controller, oracle, chain):
        # fast forward to get maximum time since last oracle update
        chain.mine(1, timestamp = chain.pending_timestamp + 1*2)

        update_interval = 100 * 10**18
        target_time = 1800 * 10**18
        error = (update_interval - params.target_time_since) * 10**18 // update_interval
        res = controller.test_update_feedback(1, error, sender=owner)
        assert not res.failed
        # TODO events
        #output = controller.last_output(1)
        #assert output != 0
        #assert output != 10**18


    def test_freeze(self, owner, controller, oracle, chain):
        """
        from addresses import oracle_addresses, gasnet_contract
        GASNET_ORACLE = gasnet_contract
        GASNET_RPC = 'https://rpc.gas.network'

        w3 = Web3(HTTPProvider(GASNET_RPC))

        with open('tests/gasnet_oracle_v2.json') as f:
            abi = json.load(f)['abi']

        oracle_gasnet = w3.eth.contract(address=GASNET_ORACLE, abi=abi)

        sid = 2
        cid = 1
        basefee_typ = 107
        tip_typ = 322

        # read gasnet
        a: bytes = oracle_gasnet.functions.getValues(sid, cid).call()
        """

        #a += DELIMITER

        typ_values = {107: random.randint(1, 10**18), 199: random.randint(1, 10**18), 322: random.randint(1, 10**18)}
        ts = int(time.time() * 1000)
        sid = 2
        cid = 1
        payload_params = {
            "plen": len(typ_values),
            "ts": ts + 2000,
            "sid": sid, 
            "cid": cid, 
            "height": 1,
            "typ_values": typ_values
            }    

        a = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)


        assert controller.oracle() == oracle.address

        with pytest.raises(Exception):
            controller.freeze()

        controller.freeze(sender=owner)

        with pytest.raises(Exception):
            controller.update_many(a, sender=owner);

        controller.unfreeze(sender=owner)
         
        controller.update_many(a, sender=owner)

    def test_update_oracle(self, owner, controller, oracle, chain):
        n = 10
        scales = [(2, 1, 10**18)]
        controller.set_scales(scales, sender=owner)

        sid = 2
        cid = 1
        for i in range(n):
            typ_values = {107: random.randint(1, 10**18), 199: random.randint(1, 10**18), 322: random.randint(1, 10**18)}
            ts = int(time.time() * 1000)
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": i,
                "typ_values": typ_values
                }

            a = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)
            tx = controller.update_many(a, sender=owner)

    def test_update_many_multi(self, owner, controller, oracle, chain):
        GASNET_ORACLE = gasnet_contract
        GASNET_RPC = 'https://rpc.gas.network'

        w3 = Web3(HTTPProvider(GASNET_RPC))

        with open('tests/gasnet_oracle_v2.json') as f:
            abi = json.load(f)['abi']

        oracle_gasnet = w3.eth.contract(address=GASNET_ORACLE, abi=abi)

        sid = 2
        cid_1 = 1
        cid_2 = 10
        basefee_typ = 107
        tip_typ = 322

        controller.set_scale(sid, cid_1, 10**15, sender=owner)
        controller.set_scale(sid, cid_2, 10**15, sender=owner)
        # read gasnet
        a: bytes = oracle_gasnet.functions.getValues(sid, cid_1).call()
        b: bytes = oracle_gasnet.functions.getValues(sid, cid_2).call()
        new_payload = a + DELIMITER + b

        rewards = controller.update_many.call(new_payload)

        tx = controller.update_many(new_payload, raise_on_revert=True, sender=owner)
        assert len(tx.events) == 2

        print("first update")
        for e in tx.events:
            print(e.event_name)
            print(e.event_arguments)
            print(f"{e.block_number=}")

        tx = controller.update_many(new_payload, sender=owner)
        # no update
        assert len(tx.events) == 0

    def test_get_updaters_chunk(self, owner, controller, oracle, chain):
        scales = [(2, 1, 10**18)]
        controller.set_scales(scales, sender=owner)

        n_updaters = 10
        for i in range(n_updaters):
            # setting balance doesn't work with test provider?
            updater = accounts.test_accounts.generate_test_account()
            updater.balance += 10**18

            # build multi-chain payload
            payload = b''
            typ_values = {107: random.randint(10**15, 10**18),
                          199: random.randint(10**15, 10**18),
                          322: random.randint(10**15, 10**18)}

            ts = int(time.time() * 1000)
            sid = 2
            cid = 1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": (i+1)*100,
                "typ_values": typ_values
                }
       
            # payload + signature
            payload = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

            rewards = controller.update_many.call(payload)
            tx = controller.update_many(payload, sender=updater)
            assert len(tx.events) != 0
            assert controller.n_updaters() == i + 1

        total_rewards_1 = [(x[0], x[1]) for x in controller.get_updaters_chunk(0, 1)]
        total_rewards_2 = [(x[0], x[1]) for x in controller.get_updaters_chunk(1, 1)]
        total_rewards_3 = [(x[0], x[1]) for x in controller.get_updaters_chunk(2, 8)]

        total_rewards = [(x[0], x[1]) for x in controller.get_updaters_chunk(0, 10)]

        assert [total_rewards_1[0], total_rewards_2[0]] + total_rewards_3[:8] == total_rewards[:10]

        assert controller.n_updaters() == n_updaters

    def test_update_many_multi_sig(self, owner, controller, oracle, chain):
        n = 3
        scales = [(2, i+1, (i+1)*10**18) for i in range(n)]
        controller.set_scales(scales, sender=owner)

        print("Values before")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)
            print(f"{i=}, {bf_value=}, {bf_height=}, {bf_ts=}")
            print(f"{i=}, {tip_value=}, {tip_height=}, {tip_ts=}")

        # build multi-chain payload
        payload = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18),
                          199: random.randint(10**15, 10**18),
                          322: random.randint(10**15, 10**18)}

            ts = int(time.time() * 1000)
            sid = 2
            cid = i+1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": (i+1)*100,
                "typ_values": typ_values
                }

            # payload + signature
            new_payload = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

            if i != 0:
                payload += DELIMITER

            payload += new_payload

        rewards = controller.update_many.call(payload)

        """
        # ensure first n time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i == n:
                break
            assert time_reward != 0
            assert dev_reward != 0
            
        """

        tx = controller.update_many(payload, raise_on_revert=True, sender=owner)
        tx.show_trace(True)
        #tx = controller.update_oracle(payload, raise_on_revert=True, sender=owner)
        assert len(tx.events) == n

        print("Values after first update")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)
            print(f"{i=}, {bf_value=}, {bf_height=}, {bf_ts=}")
            print(f"{i=}, {tip_value=}, {tip_height=}, {tip_ts=}")


        print("first update")
        for e in tx.events:
            print(e.event_name)
            print(e.event_arguments)
            print(f"{e.block_number=}")

        tx = controller.update_many(payload, sender=owner)
        # no update
        assert len(tx.events) == 0

        print("Values after first update")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)

    def test_update_many_partial_update(self, owner, controller, oracle, chain):
        # not all estimates update
        n = 3
        scales = [(2, i+1, (i+1)*10**18) for i in range(n)]
        controller.set_scales(scales, sender=owner)

        ts = int(time.time() * 1000)

        # build multi-chain payload
        payload = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18),
                          199: random.randint(10**15, 10**18),
                          322: random.randint(10**15, 10**18)}

            sid = 2
            cid = i+1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": (i+1)*100,
                "typ_values": typ_values
                }

            new_payload = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

            if i != 0:
                payload += DELIMITER

            payload += new_payload

        # build multi-chain payload #2 with only 1 new estimate
        payload2 = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18),
                          199: random.randint(10**15, 10**18),
                          322: random.randint(10**15, 10**18)}
            sid = 2
            sid = 2
            cid = i+1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": (i+1)*100,
                "typ_values": typ_values
                }
            # make one different so it succeeds
            if i == 1:
                payload_params['height'] +=1
                payload_params['ts'] += 2000

            new_payload = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

            if i != 0:
                payload2 += DELIMITER

            payload2 += new_payload

        # first update, call
        rewards = controller.update_many.call(payload)
        #print("rewards")
        #print(rewards)

        """
        receipts = oracle.storeValuesWithReceipt.call(payload)
        print("receipts")
        print(receipts)
        """

        # ensure first n time and dev rewards are non-zero
        for i, r in enumerate(rewards):
            if i == n:
                break
            assert r[4] != 0
            assert r[5] != 0

        tx = controller.update_many(payload, sender=owner)
        #oracle.storeValuesWithReceipt(payload, sender=owner)
        #print("rewards")

        events = list(tx.decode_logs())
        assert len(tx.events) == n

        """
        receipts = oracle.storeValuesWithReceipt.call(payload2)
        print("receipts2")
        print(receipts)
        """

        # second update, call
        rewards = controller.update_many.call(payload2)
        #print("rewards2")
        #print(rewards)

        # ensure only i=1 time and dev rewards are non-zero
        for i, r in enumerate(rewards):
            if i == 1:
                assert r[4] != 0
                assert r[5] != 0
            else:
                assert r[4] == 0
                assert r[5] == 0

        # second update
        tx = controller.update_many(payload2, sender=owner)
        # only 1 update
        assert len(tx.events) == 1

    def test_update_many_w_dupes(self, owner, controller, oracle, chain):
        n = 5
        scales = [(2, i+1, (i+1)*10**18) for i in range(n)]
        controller.set_scales(scales, sender=owner)

        # constant cid, time and height for all payloads
        cid = 1
        ts = 2000
        height = 100

        # build multi-chain payload
        payload = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18), 199: random.randint(10**15, 10**18), 322: random.randint(10**15, 10**18)}
            sid = 2
            cid = 1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts,
                "sid": sid,
                "cid": cid,
                "height": height,
                "typ_values": typ_values
                }

            new_payload = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

            if i != 0:
                payload += DELIMITER

            payload += new_payload

        rewards = controller.update_many.call(payload)

        # ensure first n time and dev rewards are non-zero
        for i, r in enumerate(rewards):
            if i != 0:
                assert r[4] == r[5] == 0

        tx = controller.update_many(payload, sender=owner);

        # only the first paylaod should receive an update
        assert len(tx.events) == 1

        # same payload should produce zero updates
        tx = controller.update_many(payload, sender=owner);
        assert len(tx.events) == 0

    def _test_update_oracle_max_reward(self, owner, controller, chain):
        # fast forward to get maximum time since last oracle update
        #chain.mine(1800, timestamp = chain.pending_timestamp + 1800*2)

        assert controller.rewards(owner) == 0
        tx = controller.update_oracle_mock(1, 1900*10**18, 300, sender=owner);
        # right after deploy, large deviation, but small time reward
        assert controller.rewards(owner) == params.min_reward//2 + params.max_reward//2

    def _test_update_oracle_min_reward(self, owner, controller, chain):

        # first update
        tx = controller.update_oracle_mock(1, 1900*10**18, 300, sender=owner);

        first_balance = controller.rewards(owner)

        # immediately update again
        tx2 = controller.update_oracle_mock(1, 1900*10**18, 301, sender=owner);

        """
        events = list(tx2.decode_logs())

        e = events[0]

        assert len(events) == 1

        assert e.reward == params.min_reward
        assert controller.rewards(owner) == first_balance + params.min_reward
        """

    def test_rewards(self, controller, oracle, owner):

        sid = 2
        cid = 1
        ts = int(time.time() * 1000)

        # update #1
        gas_price = int(1e9)
        typ_values = utils.create_typ_values(gas_price)

        payload_params = {
            "plen": len(typ_values),
            "ts": ts,
            "sid": sid,
            "cid": cid,
            "height": 100,
            "typ_values": utils.create_typ_values(gas_price)
            }

        a = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

        rewards_before_a = controller.rewards(owner)
        print(f"{rewards_before_a=}")
        controller.update_many(a, sender=owner)

        _, current_height, current_ts = oracle.get(sid, cid, 107)
        rewards_after_a = controller.rewards(owner)
        print(f"{rewards_after_a=}")

        # update #2, gas spike
        gas_price = int(10e9)
        typ_values = utils.create_typ_values(gas_price)

        payload_params = {
            "plen": len(typ_values),
            "ts": ts + 1000,
            "sid": sid,
            "cid": cid,
            "height": 101,
            "typ_values": utils.create_typ_values(gas_price)
            }
        print(payload_params)

        _, current_height, current_ts = oracle.get(sid, cid, 107)
        print(f"{current_height=}, {current_ts=}")

        b = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

        controller.update_many(b, sender=owner)
        rewards_after_b = controller.rewards(owner)
        print(f"{rewards_after_b=}")

        # update #3, same gas, same time
        gas_price = int(10e9)
        typ_values = utils.create_typ_values(gas_price)

        payload_params = {
            "plen": len(typ_values),
            "ts": ts + 2000,
            "sid": sid,
            "cid": cid,
            "height": 101,
            "typ_values": utils.create_typ_values(gas_price)
            }
        print(payload_params)

        _, current_height, current_ts = oracle.get(sid, cid, 107)
        print(f"{current_height=}, {current_ts=}")

        c = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)


        controller.update_many(c, sender=owner)
        rewards_after_c = controller.rewards(owner)
        print(f"{rewards_after_c=}")

        # update #4, same gas, large time diff
        gas_price = int(10e9)
        typ_values = utils.create_typ_values(gas_price)

        payload_params = {
            "plen": len(typ_values),
            "ts": ts + 4000000,
            "sid": sid,
            "cid": cid,
            "height": 102,
            "typ_values": utils.create_typ_values(gas_price)
            }
        print(payload_params)

        _, current_height, current_ts = oracle.get(sid, cid, 107)
        print(f"{current_height=}, {current_ts=}")

        d = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

        controller.update_many(d, sender=owner)
        rewards_after_d = controller.rewards(owner)
        print(f"{rewards_after_d=}")

        # update #5, large gas diff, large time diff
        gas_price = int(100e9)
        typ_values = utils.create_typ_values(gas_price)

        payload_params = {
            "plen": len(typ_values),
            "ts": ts + 9999000000,
            "sid": sid,
            "cid": cid,
            "height": 1020000,
            "typ_values": utils.create_typ_values(gas_price)
            }
        print(payload_params)

        _, current_height, current_ts = oracle.get(sid, cid, 107)
        print(f"{current_height=}, {current_ts=}")

        e = utils.create_signed_payload(web3=web3, signer=owner, **payload_params)

        controller.update_many(e, sender=owner)
        rewards_after_e = controller.rewards(owner)
        print(f"{rewards_after_e=}")

    def test_calc_deviation(self, owner, controller):
        controller.set_scale(2, 1, 3*10**15, sender=owner)
        scid = (1 << 8) | 2
        # how many IQRs is 
        assert controller.calc_deviation(scid, abs(10*10**15 - 1*10**15)) == 3*10**18
        assert controller.calc_deviation(scid, abs(1*10**15 - 10*10**15)) == 3*10**18
        assert controller.calc_deviation(scid, abs(1*10**15 - 4*10**15)) == 1*10**18
        assert controller.calc_deviation(scid, abs(4*10**15 - 1*10**15)) == 1*10**18
        assert controller.calc_deviation(scid, abs(5*10**15 - 5*10**15)) == 0

        #zero scale should revert
        with pytest.raises(Exception):
            controller.set_scale(2, 1, 0, sender=owner)
            controller.calc_deviation(1, abs(10*10**15 - 1*10**15))


    def test_update_interval_ema(self, owner, controller):
        vals = [random.randint(600 * 10**18, 30000 * 10**18) for _ in range(100)]
        data = []
        means = []
        emas = []
        for v in vals:
            controller.test_update_interval_ema(1, v, sender=owner)
            data.append(v)
            means.append(np.mean(data[-10:])/10**18)
            emas.append(controller.interval_ema(1)/10**18)


        # Uncomment to see comparative plot
        """
        plt.plot(means, label='mean')
        plt.plot(emas, label='ema')
        plt.legend()
        plt.show()
        """


