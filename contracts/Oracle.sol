// SPDX-License-Identifier: MIT
pragma solidity ^0.8.13;

contract Oracle {
    address private owner;

    mapping(address => bool) private signers;
    mapping(uint88 => Record) private pStore;

    constructor() {
        owner = msg.sender;
    }

    struct RecordReceipt {
        RecordKey record;
        Record old_record;
        Record new_record;
    }

    struct Record  {
        uint64 height;
        uint48 timestamp;
        uint240 value;
    }

    struct RecordKey {
        uint8 systemid;
        uint64 cid;
        uint16 typ;
    }

    struct v1Header {
        uint8 version;
        uint16 payloadlen;
        uint88 scid;
        uint8 sid;
        uint64 cid;
        uint48 ts;
        uint64 height;
    }

    // owner override for fixing values
    function ownerSetValues(
        uint8 systemid,
        uint64 cid,
        uint16 typ,
        uint48 timestamp,
        uint64 height,
        uint240 value
    ) public {
        assert(owner == msg.sender);

        Record storage r = pStore[getKey(systemid, cid, typ)];
        r.timestamp = timestamp;
        r.height = height;
        r.value = value;
    }

    function setSignerAddress(address s) public {
        setSignerAddress(s, true);
    }

    function setSignerAddress(address s, bool access) public {
        assert(owner == msg.sender);
        signers[s] = access;
    }

    function transferOwnership(address o) public {
        assert(owner == msg.sender);
        owner = o;
    }

    function storeValues(bytes memory dat) public {
        uint init;
        uint offset;
        assembly {
            init := add(dat, 0x20) // skip bytes header (length parameter)
            offset := init
        }

        // header
        uint8 version;
        uint16 payloadlen;
        uint88 scid;
        uint48 ts;
        uint64 height;
        // payload
        uint256 val;
        uint16 typ;

        address recovered;
        while (true) {
            if (offset >= init + dat.length) {
                break;
            }

            (version, payloadlen, scid, ts, height) = decodeHeader(offset);
            if (version == 0) {
                break;
            }

            recovered = checkSignature(payloadlen, offset);
            require(recovered != address(0), "ECDSA: invalid signature");
            require(signers[recovered], "invalid signer");

            uint start = offset + 0x20; // skip header
            uint8 j;
            while (j < payloadlen) {
                assembly {
                    val := mload(add(start, mul(0x20, j)))
                    typ := shl(0x8, byte(0, val))
                    typ := add(typ, byte(1, val))
                }
                scid = appendType(scid, typ);
                Record storage rec = pStore[scid];

                if (rec.height < height) {
                    pStore[scid] = Record(height, ts, uint240(val));
                } else if (rec.height == height && rec.timestamp < ts) {
                    pStore[scid] = Record(height, ts, uint240(val));
                }
                j++;
            }

            offset += (payloadlen + 4) * 0x20; // ( payload + header + signature )
        }
    }



    function storeValuesWithReceipt(bytes memory dat) public returns (RecordReceipt[] memory receipts) {
        uint init;
        uint offset;
        assembly {
            init := add(dat, 0x20) // skip bytes header (length parameter)
            offset := init
        }
 
        uint elWritten = 0;
        uint elCount = payloadElementsCount( offset, dat.length+init );
        RecordReceipt[] memory r = new RecordReceipt[](elCount);
        

        address recovered;
        // payload
        uint256 val;
        uint16 typ;

        while (true) {
            if (offset >= init + dat.length) {
                break;
            }

            v1Header memory header = decodeHeaderStruct(offset);
            if (header.version == 0) {
                break;
            }

            recovered = checkSignature(header.payloadlen, offset);
            require(recovered != address(0), "ECDSA: invalid signature");
            require(signers[recovered], "invalid signer");

            uint start = offset + 0x20; // skip header
            uint8 j;
            uint88 scid;
            while (j < header.payloadlen) { 
                assembly {
                    val := mload(add(start, mul(0x20, j)))
                    typ := shl(0x8, byte(0, val))
                    typ := add(typ, byte(1, val))
                }
                scid = appendType(header.scid, typ);

                Record storage rec = pStore[scid];
                if (rec.height < header.height) {
                    r[elWritten] = RecordReceipt(RecordKey(header.sid, header.cid, typ), rec, Record(header.height, header.ts, uint240(val)));
                    pStore[scid] = Record(header.height, header.ts, uint240(val));
                    
                } else if (rec.height == header.height && rec.timestamp < header.ts) {
                    receipts[elWritten] = RecordReceipt(RecordKey(header.sid, header.cid, typ), rec, Record(header.height, header.ts, uint240(val)));
                    pStore[scid] = Record(header.height, header.ts, uint240(val));
                  
                }
                elWritten +=1;
                j++;
            }

            offset += (header.payloadlen + 4) * 0x20; // ( payload + header + signature )
        } 

        return r;
    }


    function payloadElementsCount(uint offset, uint lastOffset ) private pure returns (uint) {
  
        uint count = 0;

        bytes32 buf;
        uint8 version;
        uint16 payloadlen;
        while (true) { 
            if (offset >= lastOffset) {
                break;
            }

            assembly { 
                buf := mload(offset) 
                version := buf
                buf := shr(0xC0, buf)
                payloadlen := buf
            }
 
            if (version == 0) {
                break;
            } 
            count += payloadlen;
            offset += (payloadlen + 4) * 0x20; // ( payload + header + signature )
        }

        return count;

    }


    function decodeHeaderStruct(
        uint offset
    )
        private
        pure
        returns (
            v1Header memory header
        )
    {
        bytes32 buf;
        uint8 version;
        uint16 payloadlen;
        uint88 scid;
        uint8 sid;
        uint64 cid;
        uint48 ts;
        uint64 height;

        assembly {
           // HEADER
           buf := mload(offset)

           // decode version
           version := buf

           // shift 8 + decode height
           buf := shr(0x08, buf)
           height := buf

           // shift 64 + decode chain id
           buf := shr(0x40, buf)
           cid := buf

           // shift 64 + decode service id
           buf := shr(0x40, buf)
           sid := buf

           // shift 8 + decode timestamp
           buf := shr(0x08, buf)
           ts := buf

           // shift 48 + decode estimations length
           buf := shr(0x30, buf)
           payloadlen := buf

           scid := sid
           scid := shl(0x40, scid)
           scid := cid
           scid := shl(0x10, scid)
        }

        return (v1Header(version, payloadlen, scid, sid, cid, ts, height));
    }

    function decodeHeader(
        uint offset
    )
        private
        pure
        returns (
            uint8 version,
            uint16 payloadlen,
            uint88 scid,
            uint48 ts,
            uint64 height
        )
    {
        bytes32 buf;
        uint8 sid;
        uint64 cid;
        assembly {
            // HEADER
            buf := mload(offset)

            // decode version
            version := buf

            // shift 8 + decode height
            buf := shr(0x08, buf)
            height := buf

            // shift 32 + decode chain id
            buf := shr(0x40, buf)
            cid := buf

            // shift 32 + decode service id
            buf := shr(0x40, buf)
            sid := buf

            // shift 8 + decode timestamp
            buf := shr(0x08, buf)
            ts := buf

            // shift 48 + decode estimations length
            buf := shr(0x30, buf)
            payloadlen := buf

            scid := sid
            scid := shl(0x40, scid)
            scid := cid
            scid := shl(0x10, scid)
        }

        return (version, payloadlen, scid, ts, height);
    }

    function checkSignature(
        uint16 payloadlen,
        uint offset
    ) private pure returns (address recovered) {
        bytes32 r;
        bytes32 s;
        uint8 v;
        bytes32 kec;

        assembly {
            // SIGNATURE

            // calc signature's contents length
            // (header + payload  ( 0x20 + 0x20 * num. elements ) )
            let siglen := add(0x20, mul(0x20, payloadlen))

            // hash content
            kec := keccak256(offset, siglen)

            // shift + decode r
            offset := add(offset, siglen)
            r := mload(offset)

            // shift + decode s
            offset := add(offset, 0x20)
            s := mload(offset)

            // shift + decode v
            offset := add(offset, 0x20)
            v := byte(0, mload(offset))
        }

        if (v != 27 && v != 28) {
            revert("invalid signer v param");
        }

        recovered = ecrecover(kec, v, r, s);
    }

    function appendType(
        uint88 scida,
        uint16 typ
    ) private pure returns (uint88 scidb) {
        assembly {
            scidb := shr(0x10, scida)
            scidb := shl(0x10, scidb)
            scidb := add(scidb, typ)
        }
        return scidb;
    }

    function get(
        uint8 systemid,
        uint64 cid,
        uint16 typ
    ) public view returns (uint256 value, uint64 height, uint48 timestamp) {
        Record storage s = pStore[getKey(systemid, cid, typ)];
        return (uint256(s.value), s.height, s.timestamp);
    }

    function getValue(
        uint8 systemid,
        uint64 cid,
        uint16 typ
    ) public view returns (uint256 value) {
        Record storage s = pStore[getKey(systemid, cid, typ)];
        return uint256(s.value);
    }

    function getRecord(
        uint8 systemid,
        uint64 cid,
        uint16 typ
    ) public view returns (Record memory r) {
        return pStore[getKey(systemid, cid, typ)];
    }

    function getInTime(
        uint8 systemid,
        uint64 cid,
        uint16 typ,
        uint48 tin
    ) public view returns (uint256 value, uint64 height, uint48 timestamp) {
        Record storage s = pStore[getKey(systemid, cid, typ)];
        if (s.timestamp >= uint48(block.timestamp) * 1000 - tin) {
            return (uint256(s.value), s.height, s.timestamp);
        }

        return (0, 0, 0);
    }

    function getKey(
        uint8 sid,
        uint64 cid,
        uint16 typ
    ) private pure returns (uint88 scid) {
        assembly {
            scid := sid
            scid := shl(0x40, scid)

            scid := add(scid, cid)
            scid := shl(0x10, scid)

            scid := add(scid, typ)
        }
        return (scid);
    }

    function getRecords( uint88[] calldata keys ) public view returns ( Record[] memory records) { 
        records = new Record[](keys.length);
        for (uint i = 0; i < keys.length; i++) {
            records[i] = pStore[keys[i]];
        }
        return records;
    }

    function getRecords( RecordKey[] calldata keys ) public view returns ( Record[] memory records) { 
        records = new Record[](keys.length);
        for (uint i = 0; i < keys.length; i++) {
            records[i] = pStore[getKey(keys[i].systemid, keys[i].cid, keys[i].typ)];
        }
        return records;
    }
}
