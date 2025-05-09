# rewardcontroller

## Dependencies and Setup

tested w/ Python 3.11

`python -m venv venv`
`source venv/bin/activate`
`pip install -r requirements.txt`

#### Ape Config

Create `ape-config.yaml` in root dir.
```
ethereum:
  default_network: local
  local:
    host: http://127.0.0.1
    port: 8545

  sepolia:
    infura:
      uri: <ETH SEPOLIA INFURA URL>
base:
  sepolia:
    infura:
      uri: <BASE SEPOLIA INFURA URL>
vyper:
  version: 0.4.1
  settings:
    optimize: false
```


## Tests

`ape test tests/test_rewardcontroller.py`


## Scripts

#### Set Infura API Key

`export WEB3_INFURA_API_KEY=<KEY>`

### Deploy
`ape run scripts/deploy.py --network ethereum:sepolia:infura`

### Set Scales

Scales are set per-network and allow the contract to use a single reward function that operates on standardized price deviations.

`ape run scripts/set_scales.py --network ethereum:sepolia:infura`

scales are defined in `scripts/params.py` and can should be periodically refreshed from the ETL notebook

#### Databricks Scale Notebook

https://github.com/blocknative/analytics/blob/main/ETL/rewards/Reward%20Contract%3A%20Extract%20Gas%20Prices%2C%20S3.py

### Update

`ape run scripts/update.py --network ethereum:sepolia:infura`
