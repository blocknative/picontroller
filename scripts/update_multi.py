import json
import time
import ape
import pytest
from web3 import Web3, HTTPProvider
from eth_abi import decode

from ape import accounts, networks
from ape import Contract
from ape import project

from scripts.abis import gas_oracle_v2_abi
from scripts import params
from scripts.oracles import oracle_addresses

SEPOLIA_ORACLE = oracle_addresses[11155111]#'0xCc936bE977BeDb5140C5584d8B6043C9068622A6'
REWARDS = '0xd1aC001f243E61682167D1177fAd4182C956E493'
controller = project.RewardController.at(REWARDS)

# Gasnet
w3 = Web3(HTTPProvider('https://rpc.gas.network'))
address = '0x4245Cb7c690B650a38E680C9BcfB7814D42BfD32'
with open('tests/gasnet_oracle_v2.json') as f:
    abi = json.load(f)['abi']
oracle_gasnet = w3.eth.contract(address=address, abi=abi)

account = accounts.load("blocknative_dev")

rewards_before = controller.rewards(account)
total_rewards = controller.total_rewards()
print(f"{rewards_before=}")
print(f"{total_rewards=}")

sid = 2
cid_1 = 42161
cid_2 = 10
tip_typ = params.tip_reward_type

# read gasnet
dat_1: bytes = oracle_gasnet.functions.getValues(sid, cid_1).call()
dat_2: bytes = oracle_gasnet.functions.getValues(sid, cid_2).call()
d = b'0000000000000000000000000000000'
dat = dat_1 + d + dat_2

rewards = controller.update_many.call(dat)
print("pending rewards")
print(rewards)

# update oracle w/ gasnet payload
tx = controller.update_many(dat, sender=account, raise_on_revert=True, gas=3000000)
tx.show_trace(True)

print(tx.events)

rewards_after = controller.rewards(account)
print(f"{rewards_after=}")
reward_emitted = (rewards_after - rewards_before)
print(f"{reward_emitted=}")
print(f"{reward_emitted/10**18=}")
