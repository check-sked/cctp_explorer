import asyncio
from web3 import AsyncWeb3
from web3.middleware import async_geth_poa_middleware
from datetime import datetime
import csv

def setup_web3_provider(url):
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url))
    w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
    return w3

w3_eth = setup_web3_provider('https://avax-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')

MESSAGE_TRANSMITTER = AsyncWeb3.to_checksum_address('0x8186359af5f57fbb40c6b14a588d2a59c0c29880')
MESSAGE_RECEIVED_EVENT = '0x58200b4c34ae05ee816d710053fff3fb75af4395915d3d2a771b24aa10e3cc5d'

DOMAIN_TO_CHAIN = {
    0: 'ethereum', 1: 'avalanche', 2: 'optimism', 3: 'arbitrum',
    4: 'noble', 5: 'solana', 6: 'base', 7: 'polygon', 8: 'sui'
}

def decode_uint256(hex_data):
    return int.from_bytes(hex_data, byteorder='big')

def decode_address(hex_data):
    if isinstance(hex_data, str):
        clean_hex = hex_data.replace('0x', '')
        return AsyncWeb3.to_checksum_address('0x' + clean_hex[-40:])
    else:
        hex_str = hex_data.hex()
        if hex_str.startswith('0x'):
            hex_str = hex_str[2:]
        return AsyncWeb3.to_checksum_address('0x' + hex_str[-40:])

async def get_cctp_transfers_in(start_block, end_block, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'block_number',
            'transaction_hash',
            'timestamp',
            'caller',
            'source_chain',
            'nonce',
            'sender',
            'recipient',
            'complexity'
        ])
    
    logs = await w3_eth.eth.get_logs({
        'address': MESSAGE_TRANSMITTER,
        'fromBlock': start_block,
        'toBlock': end_block,
        'topics': [MESSAGE_RECEIVED_EVENT]
    })
    
    for log in logs:
        try:
            block = await w3_eth.eth.get_block(log['blockNumber'])
            tx = await w3_eth.eth.get_transaction(log['transactionHash'])
            
            receipt = await w3_eth.eth.get_transaction_receipt(log['transactionHash'])
            complexity = len(receipt['logs'])
            
            caller = decode_address(log['topics'][1])
            nonce = int(log['topics'][2].hex(), 16)
            
            data = log['data']
            source_domain = decode_uint256(data[0:32])
            sender = decode_address(data[32:64])
            
            message_body = data[64:]
            recipient = decode_address(message_body[96:128])
            
            source_chain = DOMAIN_TO_CHAIN.get(source_domain, f"Unknown ({source_domain})")
            
            with open(output_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    log['blockNumber'],
                    log['transactionHash'].hex(),
                    datetime.utcfromtimestamp(block['timestamp']).strftime('%Y-%m-%d %H:%M:%S'),
                    caller,
                    source_chain,
                    nonce,
                    sender,
                    recipient,
                    complexity
                ])
            
            print(f"Processed incoming transfer #{nonce} from {source_chain} in block {log['blockNumber']}")
            
        except Exception as e:
            print(f"Error processing log: {str(e)}")
            continue

async def main():
    end_block = await w3_eth.eth.block_number
    start_block = end_block - 10000  # Last 1000 blocks
    await get_cctp_transfers_in(start_block, end_block, 'avalanche_transfers_in.csv')

if __name__ == "__main__":
    asyncio.run(main())