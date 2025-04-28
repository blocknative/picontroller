import json
import time
import ape
import pytest
from web3 import Web3, HTTPProvider
from eth_abi import decode

from ape import accounts, networks
from ape import Contract
from ape import project, chain

from scripts.abis import gas_oracle_v2_abi
from scripts import params
from scripts.addresses import oracle_addresses, reward_addresses

REWARDS = reward_addresses[chain.chain_id]
controller = project.RewardController.at(REWARDS)

def set_scales(account, controller, params):
    scales = [(x[0][0], x[0][1], x[1]) for x in list(zip(params.scales.keys(), params.scales.values()))]
    controller.set_scales(scales, sender=account)
    for s in scales:
        print(s)

account = accounts.load("blocknative_dev")
set_scales(account, controller, params)
