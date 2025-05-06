import sys
import ape

from ape import accounts
from ape import project, chain

from scripts.addresses import reward_addresses

rewards = reward_addresses[chain.chain_id]
controller = project.RewardController.at(rewards)

account = accounts.load("blocknative_dev")

rewards_off = controller.rewards_off()

print(f"{rewards_off=}")

if rewards_off == False:
    print("Rewards are already on. Exiting.")
    sys.exit()


tx = controller.turn_rewards_on(sender=account)
