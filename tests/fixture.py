import pytest
from ape import accounts, Contract
import params

from addresses import oracle_addresses
from abis import gas_oracle_v3_abi

SEPOLIA_ORACLE = oracle_addresses[11155111]

@pytest.fixture
def oracle(owner, project):
    oracle = owner.deploy(project.Oracle, sender=owner)
    # assign owner so we can create payloads
    oracle.setSignerAddress(owner.address, sender=owner)
    # assign gasnet signer so we can use gasnet payloads
    oracle.setSignerAddress("0x26222b1a8C061f7Ebda1f4a4d15A66683260dBE5", sender=owner)
    return oracle

@pytest.fixture
def oracle_sepolia(owner, project):
    contract = Contract(SEPOLIA_ORACLE, abi=gas_oracle_v3_abi)
    return contract

@pytest.fixture
def owner(accounts):
    return accounts[0]

@pytest.fixture
def controller(owner, oracle, project, chain):
    controller = owner.deploy(project.RewardController,
            params.kp,
            params.ki,
            params.co_bias,
            params.output_upper_bound,
            params.output_lower_bound,
            params.target_time_since,
            params.tip_reward_type,
            params.min_reward,
            params.max_reward,
            params.default_window_size,
            oracle.address,
            params.coeff,
            sender=owner)

    set_scales(owner, controller, params)
    # deploy sets last update time and updates can't happen if blocktime=lastupdatetime
    # so fast forward 1 block
    chain.mine(1, timestamp = chain.pending_timestamp + 2)
    return controller

def set_scales(account, controller, params):
    # this creates a list of (system_id, chain_id, scale) tuples
    scales = [(x[0][0], x[0][1], x[1]) for x in list(zip(params.scales.keys(), params.scales.values()))]
    controller.set_scales(scales, sender=account)
    #for s in params.scales.keys():
    #    print(s, controller.scales(s))

@pytest.fixture
def controller_sepolia(owner, project):
    controller = owner.deploy(project.RewardController,
            params.kp,
            params.ki,
            params.co_bias,
            params.output_upper_bound,
            params.output_lower_bound,
            params.target_time_since,
            params.tip_reward_type,
            params.min_reward,
            params.max_reward,
            params.default_window_size,
            SEPOLIA_ORACLE,
            params.coeff,
            sender=owner)

    set_scales(owner, controller, params)
    return controller

