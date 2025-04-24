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
from scripts.addresses import reward_addresses

DELIMITER = b'0000000000000000000000000000000'
chain_id = 84532 # base sepolia
chain_id = 11155111 # sepolia
rewards = reward_addresses[chain_id]
controller = project.RewardController.at(rewards)

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

payload = b''
for i, cid in enumerate(params.scales.keys()):
    # read gasnet
    dat: bytes = oracle_gasnet.functions.getValues(sid, cid).call()
    if i != 0:
          payload += DELIMITER
    payload += dat

rewards = controller.update_many.call(payload)
print("pending rewards")
print(rewards)

# update oracle w/ gasnet payload
tx = controller.update_many(payload, sender=account, raise_on_revert=True, gas=3000000)
tx.show_trace(True)

print(tx.events)

rewards_after = controller.rewards(account)
print(f"{rewards_after=}")
reward_emitted = (rewards_after - rewards_before)
print(f"{reward_emitted=}")
print(f"{reward_emitted/10**18=}")
