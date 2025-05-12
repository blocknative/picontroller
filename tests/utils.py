import os
from web3 import Web3

web3 = Web3()

def create_raw_payload(plen, ts, sid, cid, height, typ_values={}, version=1):
    empty = 0
    header = empty.to_bytes(6, 'big') + plen.to_bytes(2, 'big') + ts.to_bytes(6, 'big') + sid.to_bytes(1, 'big') + \
            cid.to_bytes(8, 'big') + height.to_bytes(8, 'big') + version.to_bytes(1, 'big')

    values = b''
    for typ, val in typ_values.items():
        values += typ.to_bytes(2, 'big') + val.to_bytes(30, 'big')

    return header + values

def create_signed_payload(web3, signer, plen, ts, sid, cid, height, typ_values={}, version=1):
    data = create_raw_payload(plen, ts, sid, cid, height, typ_values, version=1)
    data_h = web3.keccak(data)
    signed = signer.sign_raw_msghash(data_h)
    sig2 = signed.encode_rsv()
    payload = data + sig2

    return payload

def create_typ_values(gas_price, tip_pct=0.10):
    assert tip_pct > 0 and tip_pct <= 1
    bf_pct = 1. - tip_pct

    gp = int(bf_pct * gas_price)
    tip = int(tip_pct * gas_price)

    # check for rounding down
    if gp + tip < gas_price:
        gp += 1

    assert gp + tip == gas_price

    return {107: gp, 322: tip}


def create_final_payload(sid, cid, ts, height, gas_price, signer):
    typ_values = create_typ_values(gas_price)
    print(typ_values)

    payload_params = {
        "plen": len(typ_values),
        "sid": sid,
        "cid": cid,
        "ts": ts,
        "height": height,
        "typ_values": typ_values
        }

    return create_signed_payload(web3=web3, signer=signer, **payload_params)

def get_current_gasprice(oracle, sid, cid):
    current_bf, current_bf_height, current_bf_ts = oracle.get(sid, cid, 107)
    current_tip, current_tip_height, current_tip_ts = oracle.get(sid, cid, 322)

    assert current_bf_height == current_tip_height
    assert current_bf_ts == current_tip_ts

    return current_bf + current_tip, current_bf_height, current_bf_ts

def get_current_bf(oracle, sid, cid):
    current_bf, current_bf_height, current_bf_ts = oracle.get(sid, cid, 107)
    current_tip, current_tip_height, current_tip_ts = oracle.get(sid, cid, 322)

    assert current_bf_height == current_tip_height
    assert current_bf_ts == current_tip_ts

    return current_bf + current_tip, current_bf_height, current_bf_ts
