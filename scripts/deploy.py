import sys
from scripts.addresses import oracle_addresses
from scripts import params
import ape
from ape import accounts
from ape import project, chain

from ape_accounts import import_account_from_private_key

def deploy(params, chain_id, owner, project):
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
            oracle_addresses[chain_id],
            params.coeff,
            publish=True,
            sender=owner)

    return controller

def main():
    #chain_id = 84532 # base sepolia
    chain_id = 11155111 # sepolia
    account = accounts.load("blocknative_dev")
    controller = deploy(params, chain_id, account, project)
    print(f"{controller.address=}")
