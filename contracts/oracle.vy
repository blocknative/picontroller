#pragma version ~=0.4.0

import store

values: public(HashMap[uint64, HashMap[uint16, uint240]])
heights: public(HashMap[uint64, uint64])
update_times: public(HashMap[uint64, uint48])
MAX_PAYLOADS: public(constant(uint256)) = 32
MAX_PAYLOAD_SIZE: public(constant(uint256)) = 16384

struct RecordReceipt:
    systemid: uint8
    cid: uint64
    typ: uint16
    old_height: uint64
    old_timestamp: uint48
    old_value: uint240
    new_height: uint64
    new_timestamp: uint48
    new_value: uint240

@deploy
def __init__():
    pass

@external
@view
def get(sid: uint8, cid: uint64, typ: uint16) -> (uint240, uint64, uint48):
    return self.values[cid][typ], self.heights[cid], self.update_times[cid]
    
#@external
#def set_value(chain_id: uint64, new_value: uint256, height: uint64):
#    self.values[cid] = new_value
#    self.heights[chain_id] = height
#    self.update_times[chain_id] = convert(block.timestamp, uint48)

@external
def storeValues(dat: Bytes[MAX_PAYLOAD_SIZE]):
    sid: uint8 = 0
    cid: uint64 = 0
    basefee_val: uint240 = 0
    tip_val: uint240 = 0
    ts: uint48 = 0
    h: uint64 = 0

    #sid, cid, basefee_val, tip_val, ts, h = store._decode(dat, 322)

    #self.values[cid][107] = basefee_val
    #self.values[cid][322] = tip_val
    #self.heights[cid] = h
    #self.heights[cid] = h
    #self.update_times[cid] = ts

@external
def storeValuesWithReceipt(dat: Bytes[MAX_PAYLOAD_SIZE]) -> DynArray[RecordReceipt, MAX_PAYLOADS]:
    rr: DynArray[RecordReceipt, MAX_PAYLOADS] = empty(DynArray[RecordReceipt, MAX_PAYLOADS])
    return rr

#@external
#def storeValuesWithReceipt(dat: Bytes[MAX_PAYLOAD_SIZE]):
#    a: uint256 = 0

#def storeValuesWithReceipt():
#    a: uint256 = 0

