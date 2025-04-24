import os

def create_payload(plen, ts, sid, cid, height, typ_values={}, version=1):
    empty = 0
    header = empty.to_bytes(6, 'big') + plen.to_bytes(2, 'big') + ts.to_bytes(6, 'big') + sid.to_bytes(1, 'big') + \
            cid.to_bytes(8, 'big') + height.to_bytes(8, 'big') + version.to_bytes(1, 'big')

    values = b''
    for typ, val in typ_values.items():
        values += typ.to_bytes(2, 'big') + val.to_bytes(30, 'big')

    return header + values

def create_signed_payload(web3, signer, plen, ts, sid, cid, height, typ_values={}, version=1):
    data = create_payload(plen, ts, sid, cid, height, typ_values, version=1)
    data_h = web3.keccak(data)
    signed = signer.sign_raw_msghash(data_h)
    sig2 = signed.encode_rsv()
    payload = data + sig2

    return payload

def create_typ_values(gas_price, tip_pct=0.10):
    assert tip_pct > 0 and tip_pct <= 1
    bf_pct = 1. - tip_pct
    return {107: int(bf_pct * gas_price), 322: int(tip_pct * gas_price)}
