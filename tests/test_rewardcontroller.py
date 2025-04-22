import os
import random
import json
import time
import ape
import pytest
from web3 import Web3, HTTPProvider

from ape import accounts
from ape import Contract

import params

from fixture import owner, store, oracle, controller
import utils

TWENTY_SEVEN_DECIMAL_NUMBER = int(10 ** 27)
EIGHTEEN_DECIMAL_NUMBER     = int(10 ** 18)

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
        controller.modify_parameters_uint("default_window_size", 50, sender=owner);

        assert controller.target_time_since() ==  600
        assert controller.min_reward() ==  100
        assert controller.max_reward() ==  1000
        assert controller.default_window_size() ==  50

    def test_fail_modify_parameters_control_upper_bound(self, owner, controller):
        with ape.reverts("RewardController/invalid-output_upper_bound"):
            controller.modify_parameters_int("output_upper_bound", controller.output_lower_bound() - 1, sender=owner);
    
    def test_fail_modify_parameters_control_lower_bound(self, owner, controller):
        with ape.reverts("RewardController/invalid-output_lower_bound"):
            controller.modify_parameters_int("output_lower_bound", controller.output_upper_bound() + 1, sender=owner);

    def test_get_next_output_zero_error(self, owner, controller):
        (pi_output,_,_) = controller.get_new_pi_output(1,0);
        assert pi_output == params.co_bias + 0
        assert controller.error_integral(1) == 0

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_next_output_nonzero_error(self, owner, controller):
        error = relative_error(int(1.1E18), 10**27);
        assert error == -100000000000000000000000000

        (pi_output,_,_) = controller.get_new_pi_output(1,error);
        assert pi_output != 0
        assert controller.error_integral(1) == 0
        assert pi_output == min(params.co_bias + params.kp * int(error/10**18) + params.ki * int(error/10**18), params.output_upper_bound)

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_zero_error(self, owner, controller):
        error = relative_error(EIGHTEEN_DECIMAL_NUMBER, TWENTY_SEVEN_DECIMAL_NUMBER);
        (pi_output,_,_) = controller.get_raw_pi_output(error, 0);
        assertEq(pi_output, params.co_bias + 0);
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_nonzero_error(self, owner, controller):
        error = int(10**20)
        (pi_output,p_output,i_output) = controller.get_raw_pi_output(error, 0);
        assertEq(p_output, params.kp * int(error/1E18));
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_small_nonzero_error(self, owner, controller):
        error = int(10**18)
        (pi_output,p_output,i_output) = controller.get_raw_pi_output(error, 0);
        assert pi_output < 0
        assert p_output == params.kp * int(error/1E18)
        assert controller.error_integral(1) == 0

        # Verify did not change state
        self.check_state(owner, controller)

    def test_get_raw_output_large_nonzero_error(self, owner, controller):
        error = int(10**20) * int(10**18)
        (pi_output,p_output,i_output) = controller.get_raw_pi_output(error, 0);
        assertEq(p_output, params.kp * int(error/1E18));
        assertEq(controller.error_integral(1), 0);

        # Verify did not change state
        self.check_state(owner, controller)

    def test_first_update(self, owner, controller, chain):
        next_ts = chain.pending_timestamp
        controller.test_update(1,1, sender=owner)
        # TODO use events
        #assert controller.last_update_time(1) == next_ts
        assert controller.error_integral(1) == 1
        assert controller.error_integral(100) == 0

    def test_first_update_zero_error(self, owner, controller, chain):
        next_ts = chain.pending_timestamp
        controller.test_update(1,0, sender=owner)
        # TODO use events
        #assertEq(controller.last_update_time(1), next_ts);
        assertEq(controller.error_integral(1), 0);

    def test_two_updates(self, owner, controller, chain):
        controller.test_update(1,1, sender=owner)
        controller.test_update(1,2, sender=owner)
        assert controller.error_integral(1) != 0
        assert controller.error_integral(100) == 0

    def test_first_get_next_output(self, owner, controller):
        bias = 3*10**18
        controller.modify_parameters_control_output("co_bias", bias, sender=owner);
        # positive error
        error = controller.error(1000*10**18, 999*10**18)
        assert error > 0
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1,error);

        assert pi_output == params.kp * error//10**18  + params.ki * error//10**18 + controller.control_output().co_bias
        assert controller.error_integral(1) == 0

        # negative error
        error = controller.error(999*10**18, 1000*10**18)
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1,error);
        assert pi_output == params.kp * error//10**18  + params.ki * error//10**18 + controller.control_output().co_bias
        assert controller.error_integral(1) == 0

    def test_first_negative_error(self, owner, controller, chain):
        error = controller.error(999*10**18, 1000*10**18)
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1,error)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == params.ki * error//10**18


        next_ts = chain.pending_timestamp
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == params.ki * error//10**18

        # TODO use events
        #assert controller.last_update_time(1) == next_ts
        assert controller.error_integral(1) == error
        assert controller.error_integral(2) == 0

    def test_first_positive_error(self, owner, controller, chain):
        error = controller.error(1000*10**18, 999*10**18)
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1,error)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == params.ki * error//10**18


        next_ts = chain.pending_timestamp
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)
        assert pi_output == params.kp * error//10**18 + params.ki * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == params.ki * error//10**18

        # TODO use events
        #assert controller.last_update_time(1) == next_ts
        assert controller.error_integral(1) == error

    def test_basic_integral(self, owner, controller, chain):
        #controller.modify_parameters_int("kp", int(2.25*10**11), sender=owner);
        #controller.modify_parameters_int("ki", int(7.2 * 10**4), sender=owner);

        chain.pending_timestamp += update_delay

        error1 = controller.error(1000*10**18, 999*10**18)
        controller.test_update(1,error1, sender=owner);

        error_integral1 = controller.error_integral(1);
        assert error_integral1 == error1

        chain.pending_timestamp += update_delay

        # Second update
        error2 = controller.error(1001*10**18, 999*10**18)
        controller.test_update(1,error2, sender=owner);

        error_integral2 = controller.error_integral(1);

        assert error_integral2 == error_integral1 + error2
        return

        chain.pending_timestamp += update_delay

        # Third update
        error3 = controller.error(950*10**18, 999*10**18)
        controller.test_update(1,error3, sender=owner);
        error_integral3 = controller.error_integral(1);

        assert error_integral3, error_integral2 + error3
        
    def test_update_prate(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", int(2.25E11), sender=owner);
        controller.modify_parameters_control_output("ki", 0, sender=owner);
        chain.mine(3600, timestamp=chain.pending_timestamp+3600)

        error = relative_error(int(1.01E18), 10**27);
        assert error == -10 **25;
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)
        #assert pi_output ==  controller.output_lower_bound()
        #assert p_output == controller.kp() * error//10**18

    def test_get_next_error_integral(self, owner, controller, chain):
        update_delay = 3600
        chain.mine(update_delay//2, timestamp=chain.pending_timestamp+update_delay)

        error = controller.error(1000*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);

        assert new_integral == error
        assert new_area == error

        #update
        controller.test_update(1,error, sender=owner);
        assert controller.error_integral(1) == error

        chain.mine(update_delay//2)#, timestamp=chain.pending_timestamp+update_delay)
        next_pending_ts = chain.pending_timestamp + update_delay
        chain.pending_timestamp = next_pending_ts

        # Second update
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == error + error
        assert new_area == error
        #update
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #assert controller.last_update_time(1) == next_pending_ts
        assert controller.error_integral(1) == new_integral

        chain.pending_timestamp += update_delay

        # Third update
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        assert new_integral == 3*error
        assert new_area == error
        controller.test_update(1,error, sender=owner);
        assert controller.error_integral(1)  == 3*error

    def test_last_error(self, owner, controller, chain):
        chain.pending_timestamp += update_delay

        error = relative_error(int(1.01E18), 10**27);
        assertEq(error, -10**25);
        controller.test_update(1,error, sender=owner);

        chain.pending_timestamp += update_delay

        error = relative_error(int(1.02E18), 10**27);
        assertEq(error, -10**25 * 2);
        controller.test_update(1,error, sender=owner);

    def test_lower_bound_limit(self, owner, controller, chain):
        chain.pending_timestamp += update_delay
        # create very large error
        huge_error = controller.error(1800*10**18, 1*10**18)
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1,huge_error);

        assert pi_output == controller.output_lower_bound()

        controller.test_update(1,huge_error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)

        assert pi_output == controller.output_lower_bound()

    def test_upper_bound_limit(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", int(100e18), sender=owner);
        error = relative_error(1, 10**27);
        (pi_output, p_output, i_output) = controller.get_new_pi_output(1, error);

        assert pi_output == controller.output_upper_bound()

        controller.test_update(1, error, sender=owner);
        # TODO use events
        #(update_time, pi_output, p_output, i_output) = controller.last_update(1)
        #assertEq(pi_output, controller.output_upper_bound());

    def test_raw_output_proportional_calculation(self, owner, controller, chain):
        error = controller.error(1000*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        (pi_output, p_output, i_output) = controller.get_raw_pi_output(error, 0);
        assert pi_output == params.kp * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == 0
        
        error = controller.error(960*10**18, 999*10**18)
        (new_integral, new_area) = controller.get_new_error_integral(1, error);
        (pi_output, p_output, i_output) = controller.get_raw_pi_output(error, 0);
        assert pi_output == params.kp * error//10**18 + controller.control_output().co_bias
        assert p_output == params.kp * error//10**18
        assert i_output == 0

    def test_both_gains_zero(self, owner, controller, chain):
        controller.modify_parameters_control_output("kp", 0, sender=owner);
        controller.modify_parameters_control_output("ki", 0, sender=owner);
        assertEq(controller.error_integral(1), 0);

        error = controller.error(1000*10**18, 999*10**18)

        (pi_output, p_output, _) = controller.get_new_pi_output(1,error);
        assert pi_output == 0 + controller.control_output().co_bias
        assert p_output == 0
        assert controller.error_integral(1) == 0

    def test_lower_clamping(self, owner, controller, chain):
        assert controller.control_output().kp < 0
        assert controller.control_output().ki < 0

        chain.pending_timestamp += update_delay

        error = controller.error(1800*10**18, 1750*10**18)
        assert error > 0

        # First error: small, output doesn't hit lower bound
        controller.test_update(1,error, sender=owner);
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
        controller.test_update(1,error, sender=owner);
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

        controller.test_update(1,huge_error, sender=owner);
        # TODO use events
        #(_, pi_output3, _, _) = controller.last_update(1)
        #assert pi_output3 == controller.output_lower_bound()

        # Integral doesn't accumulate
        clamped_integral = controller.error_integral(1)
        assert clamped_integral == 2* error

        chain.pending_timestamp += update_delay

        # Integral *does* accumulate with a smaller error(doesn't hit output bound)
        controller.test_update(1,error, sender=owner);
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
        controller.test_update(1,error, sender=owner);
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
        controller.test_update(1,error, sender=owner);
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

        controller.test_update(1,huge_error, sender=owner);
        # TODO use events
        #(_, pi_output3, _, _) = controller.last_update(1)
        #assert pi_output3 == controller.output_upper_bound()

        # Integral doesn't accumulate
        clamped_integral = controller.error_integral(1)
        assert clamped_integral == 2* error

        chain.pending_timestamp += update_delay

        # Integral *does* accumulate with a smaller error(doesn't hit output bound)
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(_, pi_output4, _, _) = controller.last_update(1)
        #assert controller.error_integral(1) < clamped_integral;
        #assert pi_output4 < controller.output_upper_bound();

    def test_bounded_output_proportional_calculation(self, owner, controller, chain):
        # small error
        error = controller.error(1800*10**18, 1801*10**18)
        (pi_output, p_output, i_output) = controller.get_raw_pi_output(error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * error//10**18 + controller.control_output().co_bias
        assert p_output == controller.control_output().kp * error//10**18
        assert i_output == 0
        assert bounded_output == pi_output

        # large negative error, hits upper bound
        huge_error = controller.error(1800*10**18, 100000*10**18)
        (pi_output, p_output, i_output) = controller.get_raw_pi_output(huge_error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * huge_error//10**18 + controller.control_output().co_bias
        assert p_output == controller.control_output().kp * huge_error//10**18
        assert i_output == 0
        assert bounded_output == controller.output_upper_bound()

        # large pos error, hits lower bound
        huge_error = controller.error(1000000*10**18, 1800*10**18)
        (pi_output, p_output, i_output) = controller.get_raw_pi_output(huge_error, 0);
        bounded_output = controller.bound_pi_output(pi_output);

        assert pi_output == controller.control_output().kp * huge_error//10**18 + controller.control_output().co_bias
        assert p_output == controller.control_output().kp * huge_error//10**18
        assert i_output == 0
        assert bounded_output == controller.output_lower_bound()

    def test_last_error_integral(self, owner, controller, chain):

        chain.pending_timestamp += update_delay

        error = controller.error(1800*10**18, 1700*10**18)
        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(_, pi_output, p_output, i_output) = controller.last_update(1)
        assert controller.error_integral(1) == error

        chain.pending_timestamp += update_delay

        controller.test_update(1,error, sender=owner);
        # TODO use events
        #(_, pi_output, p_output, i_output) = controller.last_update(1)
        assert controller.error_integral(1) == error + error

        chain.pending_timestamp += update_delay
        assert controller.error_integral(1) == error + error

        controller.test_update(1,error, sender=owner);
        assert controller.error_integral(1) == error * 3

        chain.pending_timestamp += update_delay
        assert controller.error_integral(1) == error * 3

        controller.test_update(1,error, sender=owner);
        assert controller.error_integral(1) == error * 4
    # END CONTROL TESTING

    # START REWARD TESTING
    def test_set_scale(self, owner, controller, chain):
        controller.set_scale(1, 3*10**15, sender=owner)
        assert controller.scales(1) == 3*10**15

        controller.set_scale(10, 10000, sender=owner)
        assert controller.scales(10) == 10000

        controller.set_scale(10, 20000, sender=owner)
        assert controller.scales(10) == 20000
        assert controller.scales(1) == 3*10**15

    def test_set_scales(self, owner, controller, chain):
        controller.set_scales([(1, 3*10**15), (10, 10000)], sender=owner)
        assert controller.scales(1) == 3*10**15
        assert controller.scales(10) == 10000

        controller.set_scales([(1, 30*10**15), (10, 10000)], sender=owner)
        assert controller.scales(1) == 30*10**15
        assert controller.scales(10) == 10000
        controller.set_scales([(4, 40*10**15), (11, 11000)], sender=owner)
        assert controller.scales(1) == 30*10**15
        assert controller.scales(10) == 10000
        assert controller.scales(4) == 40*10**15
        assert controller.scales(11) == 11000

    def test_get_average(self, owner, controller, chain):
        assert controller.get_average(1) == 0

    def test_add_value(self, owner, controller, chain):
        controller.test_add_value(1, 5, sender=owner);
        assert controller.get_average(1) == 5
        controller.test_add_value(1, 7, sender=owner);
        assert controller.get_average(1) == 6

        assert controller.get_average(2) == 0

    def test_add_value_overflow(self, owner, controller, chain):
        assert controller.get_window_size(1) != 0
        for _ in range(controller.get_window_size(1)):
            controller.test_add_value(1, 5, sender=owner);

        assert controller.get_average(1) == 5

        controller.test_add_value(1, 10, sender=owner);

        assert controller.get_average(1) == ((controller.get_window_size(1)- 1)*5 + 10) // controller.get_window_size(1)

    def test_resize_buffer_down(self, owner, controller):
        assert controller.get_window_size(1) != 0

        for _ in range(controller.get_window_size(1)):
            controller.test_add_value(1, 5, sender=owner);

        controller.resize_buffer(1, controller.get_window_size(1)//2, sender=owner)

        assert controller.get_average(1) == 5

        for _ in range(controller.get_window_size(1)//2):
            controller.test_add_value(1, 5, sender=owner);

        for _ in range(controller.get_window_size(1)//2):
            controller.test_add_value(1, 10, sender=owner);

        controller.resize_buffer(1, controller.get_window_size(1)//2, sender=owner)

        assert controller.get_average(1) == 10

    def test_resize_buffer_up(self, owner, controller):
        orig_size = controller.get_window_size(2)
        for _ in range(orig_size):
            controller.test_add_value(2, 5, sender=owner);

        avg = controller.get_average(2)

        controller.resize_buffer(2, orig_size*2, sender=owner)
        assert controller.get_average(2) == avg

        for _ in range(orig_size):
            controller.test_add_value(2, 15, sender=owner);

        assert controller.get_average(2) == avg * 2

    def test_time_reward(self, owner, store, controller, chain):
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

    def test_deviation_reward(self, owner, store, controller, chain):
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

    def test_update(self, owner, controller, oracle, chain):
        # fast forward to get maximum time since last oracle update
        chain.mine(1, timestamp = chain.pending_timestamp + 1*2)

        update_interval = 100 * 10**18
        target_time = 1800 * 10**18
        error = (update_interval - params.target_time_since) * 10**18 // update_interval
        res = controller.test_update(1, error, sender=owner)
        assert not res.failed
        # TODO events
        #output = controller.last_output(1)
        #assert output != 0
        #assert output != 10**18

    def test_get_updaters_chunk(self, controller, oracle, chain):
        # NOTE: needs --network ethereum:local:foundry

        delimiter = b'0000000000000000000000000000000'
        n_updaters = 10
        #n_updaters = len(accounts.test_accounts)
        for i in range(n_updaters):
            # setting balance doesn't work with test provider?
            updater = accounts.test_accounts.generate_test_account()
            updater.balance += 10**18

            #updater = accounts.test_accounts[i]
            print(f"{updater.address=}")
            typ_values = {107: random.randint(1, 10**18), 199: random.randint(1, 10**18), 322: random.randint(1, 10**18)}
            ts = int(time.time() * 1000)
            sid = 2
            cid = 1
            payload_params = {
                "plen": len(typ_values),
                "ts": ts + i*2000,
                "sid": sid,
                "cid": cid,
                "height": i,
                "typ_values": typ_values
                }

            a = utils.create_payload(**payload_params)
            a+= delimiter

            with accounts.use_sender(updater):
                tx = controller.update_many(a)

            assert controller.n_updaters() == i + 1
            print(f"{tx.gas_used=}")

        updaters_1, rewards_1 = controller.get_updaters_chunk(0, 1)
        updaters_2, rewards_2 = controller.get_updaters_chunk(1, 1)
        updaters_3, rewards_3 = controller.get_updaters_chunk(2, 8)

        updaters, rewards = controller.get_updaters_chunk(0, 10)

        assert [updaters_1[0], updaters_2[0]] + updaters_3[:8] == updaters[:10]
        assert [rewards_1[0], rewards_2[0]] + rewards_3[:8] == rewards[:10]

        assert controller.n_updaters() == n_updaters

    def test_freeze(self, owner, controller, oracle, chain):

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

        a = utils.create_payload(**payload_params)

        with pytest.raises(Exception):
            controller.freeze()

        controller.freeze(sender=owner)

        with pytest.raises(Exception):
            controller.update_oracle(a, sender=owner);

        controller.unfreeze(sender=owner)
        controller.update_oracle(a, sender=owner);

    def test_update_oracle(self, owner, controller, oracle, chain):
        n = 10
        scales = [(1, 10**18)]
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

            a = utils.create_payload(**payload_params)
            tx = controller.update_oracle(a, sender=owner)

    def test_update_many_multi(self, owner, controller, oracle, chain):
        n = 2
        scales = [(i+1, (i+1)*10**18) for i in range(n)]
        controller.set_scales(scales, sender=owner)

        #assert controller.MAX_PAYLOADS() == n

        print("Values before")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)
            print(f"{i=}, {bf_value=}, {bf_height=}, {bf_ts=}")
            print(f"{i=}, {tip_value=}, {tip_height=}, {tip_ts=}")

        # build multi-chain payload
        payload = b''
        delimiter = b'0000000000000000000000000000000'
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18), 199: random.randint(10**15, 10**18), 322: random.randint(10**15, 10**18)}
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
            new_payload = utils.create_payload(**payload_params)
            print(f"{len(new_payload)=}")
            if i != 0:
                payload += delimiter
            payload += new_payload

        print(f"{len(payload)=}")
        #return
        rewards = controller.update_many.call(payload)

        #print(f"{rewards=}")

        """
        # ensure first n time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i == n:
                break
            assert time_reward != 0
            assert dev_reward != 0
            
        """

        tx = controller.update_many(payload, raise_on_revert=True, sender=owner)
        #tx = controller.update_oracle(payload, raise_on_revert=True, sender=owner)
        tx.show_trace(True)
        assert len(tx.events) == n

        print("Values after first update")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)
            print(f"{i=}, {bf_value=}, {bf_height=}, {bf_ts=}")
            print(f"{i=}, {tip_value=}, {tip_height=}, {tip_ts=}")


        events = controller.OracleUpdated.query("*")
        assert len(events) == n
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

    def test_update_oracles_partial_update(self, owner, controller, oracle, chain):
        # not all estimates update
        n = 3
        scales = [(i+1, (i+1)*10**18) for i in range(n)]
        controller.set_scales(scales, sender=owner)

        ts = int(time.time() * 1000)

        # build multi-chain payload
        payload = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18), 199: random.randint(10**15, 10**18), 322: random.randint(10**15, 10**18)}
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
            payload += utils.create_payload(**payload_params)

        # build multi-chain payload #2 with only 1 new estimate
        payload2 = b''
        for i in range(n):
            typ_values = {107: random.randint(10**15, 10**18), 199: random.randint(10**15, 10**18), 322: random.randint(10**15, 10**18)}
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
            if i == 1: # make one different so it succeeds
                payload_params['height'] +=1
                payload_params['ts'] += 2000

            # payload + signature
            payload2 += utils.create_payload(**payload_params)

        # first update, call
        rewards = controller.update_oracles.call(payload, n)

        # ensure first n time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i == n:
                break
            assert time_reward != 0
            assert dev_reward != 0
            
        tx = controller.update_oracles(payload, n, sender=owner)
        # all n update
        assert len(tx.events) == n

        # second update, call
        rewards = controller.update_oracles.call(payload2, n)

        # ensure only i=1 time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i == 1:
                assert time_reward != 0
                assert dev_reward != 0
            else:
                assert time_reward == 0
                assert dev_reward == 0

        # second update
        tx = controller.update_oracles(payload2, n, sender=owner)
        # only 1 update
        assert len(tx.events) == 1

    def test_update_oracles_w_dupes(self, owner, controller, oracle, chain):
        n = 5
        scales = [(i+1, (i+1)*10**18) for i in range(n)]
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

            # payload + signature
            payload += utils.create_payload(**payload_params)

        rewards = controller.update_oracles.call(payload, n)

        # ensure first n time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i != 0:
                assert time_reward == dev_reward == 0

        tx = controller.update_oracles(payload, n, sender=owner);

        # only the first paylaod should receive an update
        assert len(tx.events) == 1

        # same payload should produce zero updates
        tx = controller.update_oracles(payload, n, sender=owner);
        assert len(tx.events) == 0

    def test_update_oracles_case(self, owner, controller, oracle, chain):
        #payload = bytes.fromhex("00000000000000020196212416c302000000000000a4b100000000135f22c001006b0000000000000000000000000000000000000000000000000000011544f601420000000000000000000000000000000000000000000000000000000000016035523055de0bf4032e4fce04d51b4cd4bb39f8dfa4c585ceb3a40ec76e7cac7bb49848b25070cb6e0662a95501c41d399c4f11dce1a18903f6d799c7e13ee81b00000000000000020196212411300200000000000000820000000000cef9d701006b0000000000000000000000000000000000000000000000000000000000fb0142000000000000000000000000000000000000000000000000000000000001706b02b1f3c9b1e64abce149334d7b11d3e4b57345f813cb57a0e9bcc16cbad43e073c42a35381b4a3c12d1544b708d42ff35766cd4830bcfddcb572c13dac8f1b0000000000000002019621240d4802000000000000000a0000000008021ff201006b000000000000000000000000000000000000000000000000000000176f00014200000000000000000000000000000000000000000000000000000000003bb36a00263aac0a8cb4406d956f94c757bf1cfe12021c49db5a4a6744d54baaf05ade4d1a0b71bbfb6934084862755eb60818852f22d1caa490e6a065350ba38c1b000000000000000201962124057802000000000000074c00000000005547fe01006b00000000000000000000000000000000000000000000000000000000017b014200000000000000000000000000000000000000000000000000000000025341ca25683d63956d63528c12ea365d3ded79615aab6d3c541cb4b620f6fa1a3e093227e0e189fc49a487531c979ebbef03d3c081a8185cf008a891f8733d39af1b00000000000000020196212405780200000000000021050000000001b6de5c01006b000000000000000000000000000000000000000000000000000000098302014200000000000000000000000000000000000000000000000000000000003b44aede6658fc3b1cd343214ca4badac1701368a7e1bce836bace46beb6c791b30e6778c2e88592ce338c19b211d4e993edb2694d26738bb220b9052ca754bfe71b00000000000000030196212412c50200000000000000010000000001535d3d01006b00000000000000000000000000000000000000000000000000002e14b202007000000000000000000000000000000000000000000000000000004ef9325d01420000000000000000000000000000000000000000000000000000054e08413fd69156a4d6d53aa7b6a6cf272f7b908ec204cd7ddd1e75a3c56d13d31ff7cb47999b2156b238e9943b207f44207ea0b719717f6389e4cdb541f8ddaa31c1fe1c000000000000000201962124057802000000000000e70800000000011155be01006b0000000000000000000000000000000000000000000000000000000000070142000000000000000000000000000000000000000000000000000009d847683f72836213cff5480073be0f00d6a6b09c2f75a486751cc913615c8b492ac84a0cf6e3549622f8b815977a4950eccb0bfbe7848361fb48e5bcbe4a64f7129f8b1b")
        payload = bytes.fromhex("000000000000000201963b97894802000000000000074c000000000058aabf01006b00000000000000000000000000000000000000000000000000000000079801420000000000000000000000000000000000000000000000000000000001f473b0b8dbd10edf952e4674eda638856f245d4850e8b37f41646172f68edcbc864de23c107c4fbee34f308101df9c6e925f485d338e6e31209e3c81c9428961421c000000000000000201963b97936802000000000000a4b100000000137a13a501006b000000000000000000000000000000000000000000000000000000989680014200000000000000000000000000000000000000000000000000000000000a9fcd862343ce2703e198cfbf34f52005cd8c61e5009f77062bf3e68ccaadb52e3ddc87238fd750bd62fb997c1408f080de67286a4c3d1bd70bf70cc18d18eb931c000000000000000201963b97911802000000000000000a00000000080582b301006b0000000000000000000000000000000000000000000000000000000db115014200000000000000000000000000000000000000000000000000000000003ba27be7ed61351f4ec5539ba7e62173ba93af0b827e57411367cf2008f7f059e343df963f67bbc962b30222f5a5065c775549af5c5ad2ad48fe7bce0b0f1b24081b000000000000000201963b9775c002000000000000e708000000000113cc0701006b0000000000000000000000000000000000000000000000000000000000070142000000000000000000000000000000000000000000000000000002ce95f33562ae7f55f70a03ae52e6a96f062177d7b6a70a6f5d6b4d0cba5afcaf099ab5028888ae297bc6ac674b352716e290b69b0a95c6434354c4a2ede8736f950d291b000000000000000201963b978d300200000000000000820000000000d5bf5701006b0000000000000000000000000000000000000000000000000000000000fb0142000000000000000000000000000000000000000000000000000000000001e8b1e2365e7da9b2936722c65ad3438c0b3e2dd8832a5a5404c74599203fb6a502f54b578542a5ac0e6d43893fe32af341f830dee652bebc787b44d443b32a571b000000000000000301963b979190020000000000000001000000000153ed1901006b00000000000000000000000000000000000000000000000000001441e19e0070000000000000000000000000000000000000000000000000000000003d2001420000000000000000000000000000000000000000000000000000054e08404ee7c5b14a0b7b3e4f349d256c99f254936eda87d00238819463c3baec27729559b7d89804623948f4257d576975a229842834a4b2c9eb0c7c2bc34ec25478b51b000000000000000201963b9781780200000000000021050000000001ba411c01006b0000000000000000000000000000000000000000000000000000000cb9d90142000000000000000000000000000000000000000000000000000000000032eb210bc11310b713b17f29d1423e93dc75617addb961e979934cb9806c835b1248437edec8de362c5788a6622e519ab2a9916d75c682dcbbeabf78dfaa6e71dc1b")
        n = 7
        #scales = [(i+1, (i+1)*10**18) for i in range(n)]
        #controller.set_scales(scales, sender=owner)

        #assert controller.MAX_PAYLOADS() == n


        rewards = controller.update_oracles.call(payload, n)
        #print(f"{rewards=}")

        # ensure first n time and dev rewards are non-zero
        for i, (time_reward, dev_reward) in enumerate(rewards):
            if i == n:
                break
            assert time_reward != 0
            assert dev_reward != 0
            

        tx = controller.update_oracles(payload, n, sender=owner)
        assert len(tx.events) == n

        print("Values after first update")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)
            print(f"{i=}, {bf_value=}, {bf_height=}, {bf_ts=}")
            print(f"{i=}, {tip_value=}, {tip_height=}, {tip_ts=}")


        events = controller.OracleUpdated.query("*")
        assert len(events) == n
        for e in tx.events:
            print(e.event_name)
            print(e.event_arguments)
            print(f"{e.block_number=}")

        tx = controller.update_oracles(payload, n, sender=owner)
        # no update
        assert len(tx.events) == 0

        print("Values after second update")
        for i in range(n):
            bf_value, bf_height, bf_ts = oracle.get(2, i+1, 107)
            tip_value, tip_height, tip_ts = oracle.get(2, i+1, 322)

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

    def test_prepare_header(self, store, controller):
        version = 1
        height = 12345678
        chainid = 56
        systemid = 2
        ts = 9876543210
        plen = 512

        expected_value = (
            (plen << (48 + 8 + 64 + 64 + 8)) |
            (ts << (8 + 64 + 64 + 8)) |
            (systemid << (64 + 64 + 8)) |
            (chainid << (64 + 8)) |
            (height << 8) |
            version
        )
        expected_bytes32 = expected_value.to_bytes(32, byteorder='big')

        result = store.prepare_header(version, height, chainid, systemid, ts, plen)

        assert result == expected_bytes32, "Header packing failed in Vyper!"

    def test_decode_header(self, store, owner):
        # Define the input hex data as bytes
        a: bytes = bytes.fromhex("0000000000000003019460ee47e9020000000000000001000000000149dad401006b0000000000000000000000000000000000000000000000000011dab0f6ee0070000000000000000000000000000000000000000000000000000a04855e220141000000000000000000000000000000000000000000000000000005290f62089b3891d48dd725e0c8370155fee14aac001fe061f23d0c8003469af1d8e4201200d1e03e17bbfcfd866fc50d153be546ffadc022c046f1dd82441242a1f28e1c")

        plen, scid, ts, h = store.decode_header(a)
        assert h == 21617364
        assert ts == 1736793016297
        assert plen == 3
        assert scid == 2417851639229258349477888

    def test_append_type(self, store, owner):
        # Define the input hex data as bytes
        scid = 2417851639229258349477888;
        typ = 107;
        #scid: uint88 = convert(2417851639229258349477888, uint88)
        #typ: uint16 = 107

        scida = store.append_type(scid, typ)
        assert scida == scid + typ

    def test_get_key(self, store, owner):
        scid = store.get_key(2, 1, 107)
        assert scid == 2417851639229258349477888 + 107

    def test_store_values(self, store, owner):
        # Define the input hex data as bytes
        a: bytes = bytes.fromhex("0000000000000003019460ee47e9020000000000000001000000000149dad401006b0000000000000000000000000000000000000000000000000011dab0f6ee0070000000000000000000000000000000000000000000000000000a04855e220141000000000000000000000000000000000000000000000000000005290f62089b3891d48dd725e0c8370155fee14aac001fe061f23d0c8003469af1d8e4201200d1e03e17bbfcfd866fc50d153be546ffadc022c046f1dd82441242a1f28e1c")

        store.store_values(a, sender=owner)

        # Simulate block timestamp update
        #owner.provider.set_timestamp(1736793026)

        # Retrieve and validate stored data
        endf, h, ts = store.get(2, 1, 107)
        assert endf == 76683474670
        assert h == 21617364
        assert ts == 1736793016297

        endf, h, ts = store.get(2, 1, 112)
        assert endf == 43025522210
        assert h == 21617364
        assert ts == 1736793016297

        endf, h, ts = store.get(2, 1, 321)
        assert endf == 86576994
        assert h == 21617364
        assert ts == 1736793016297

    def test_get_value(self, store, owner):
        a: bytes = bytes.fromhex("0000000000000003019460ee47e9020000000000000001000000000149dad401006b0000000000000000000000000000000000000000000000000011dab0f6ee0070000000000000000000000000000000000000000000000000000a04855e220141000000000000000000000000000000000000000000000000000005290f62089b3891d48dd725e0c8370155fee14aac001fe061f23d0c8003469af1d8e4201200d1e03e17bbfcfd866fc50d153be546ffadc022c046f1dd82441242a1f28e1c")
        """
        print("first full val")
        print(a[32:64].hex())
        print("first val typ")
        print(int(a[32:64][:2].hex(), 16))

        print("second full val")
        print(a[64:96].hex())
        print("second val typ")
        print(int(a[64:96][:2].hex(), 16))

        print("3rd full val")
        print(a[96:128].hex())
        print("3rd val typ")
        print(int(a[96:128][:2].hex(), 16))
        """

        val, typ = store.get_value(a, 0)
        assert (val, typ) == (76683474670, 107)
        val, typ = store.get_value(a, 1)
        assert (val, typ) == (43025522210, 112)
        val, typ = store.get_value(a, 2)
        assert (val, typ) == (86576994, 321)

    def test_decode(self, store, owner):
        a: bytes = bytes.fromhex("0000000000000003019460ee47e9020000000000000001000000000149dad401006b0000000000000000000000000000000000000000000000000011dab0f6ee0070000000000000000000000000000000000000000000000000000a04855e220141000000000000000000000000000000000000000000000000000005290f62089b3891d48dd725e0c8370155fee14aac001fe061f23d0c8003469af1d8e4201200d1e03e17bbfcfd866fc50d153be546ffadc022c046f1dd82441242a1f28e1c")

        sid, cid, bf_val, tip_val, ts, h = store.decode(a, 107)
        assert bf_val == 76683474670
        assert sid == 2
        assert cid == 1
    def _test_rewards(self, controller, oracle, owner):

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

        a = utils.create_payload(**payload_params)

        rewards_before_a = controller.rewards(owner)
        print(f"{rewards_before_a=}")
        controller.update_oracle(a, sender=owner)

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

        b = utils.create_payload(**payload_params)

        controller.update_oracle(b, sender=owner)
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

        c = utils.create_payload(**payload_params)

        controller.update_oracle(c, sender=owner)
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

        d = utils.create_payload(**payload_params)

        controller.update_oracle(d, sender=owner)
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

        e = utils.create_payload(**payload_params)

        controller.update_oracle(e, sender=owner)
        rewards_after_e = controller.rewards(owner)
        print(f"{rewards_after_e=}")

    def test_calc_deviation(self, owner, controller):
        controller.set_scale(1, 3*10**15, sender=owner)
        assert controller.calc_deviation(1, 10*10**15, 1*10**15) == 3*10**18
        assert controller.calc_deviation(1, 1*10**15, 10*10**15) == 3*10**18
        assert controller.calc_deviation(1, 1*10**15, 4*10**15) == 1*10**18
        assert controller.calc_deviation(1, 4*10**15, 1*10**15) == 1*10**18
        assert controller.calc_deviation(1, 5*10**15, 5*10**15) == 0

        #zero scale should revert
        with pytest.raises(Exception):
            controller.set_scale(1, 0, sender=owner)
            controller.calc_deviation(1, 10*10**15, 1*10**15)



