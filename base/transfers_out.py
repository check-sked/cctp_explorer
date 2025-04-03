import asyncio
from web3 import AsyncWeb3
from web3.middleware import async_geth_poa_middleware
from datetime import datetime
import csv

def setup_web3_provider(url):
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url))
    w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
    return w3

w3_eth = setup_web3_provider('https://base-mainnet.g.alchemy.com/v2/<API_KEY>')

CIRCLE_TOKEN_MESSENGER = AsyncWeb3.to_checksum_address('0x1682Ae6375C4E4A97e4B583BC394c861A46D8962')
MESSAGE_SENT_EVENT = '0x2fa9ca894982930190727e75500a97d8dc500233a5065e0f3126c48fbe0343c0'

DOMAIN_TO_CHAIN = {
    0: 'ethereum', 1: 'avalanche', 2: 'optimism', 3: 'arbitrum',
    4: 'noble', 5: 'solana', 6: 'base', 7: 'polygon', 8: 'sui'
}

ERC20_ABI = [
    {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}
]

async def get_token_info(w3, token_address):
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    decimals = await token_contract.functions.decimals().call()
    symbol = await token_contract.functions.symbol().call()
    return decimals, symbol

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

async def analyze_transaction_type(w3, tx_hash, target_address):
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    tx = await w3.eth.get_transaction(tx_hash)
    
    is_direct = tx['to'].lower() == target_address.lower()
    total_logs = len(receipt['logs'])
    target_logs = sum(1 for log in receipt['logs'] if log['address'].lower() == target_address.lower())
    target_positions = [i for i, log in enumerate(receipt['logs']) if log['address'].lower() == target_address.lower()]
    
    return {
        'is_direct': is_direct,
        'total_logs': total_logs,
        'target_log_count': target_logs,
        'target_positions': target_positions,
        'first_contract': receipt['logs'][0]['address'] if receipt['logs'] else None
    }

async def get_cctp_transfers(start_block, end_block, output_file):
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'nonce', 'block_number', 'transaction_hash', 'timestamp', 'sender',
            'is_direct', 'total_events', 'cctp_position', 'first_contract',
            'token_address', 'token_symbol', 'amount', 'recipient', 'destination_chain'
        ])
    
    logs = await w3_eth.eth.get_logs({
        'address': CIRCLE_TOKEN_MESSENGER,
        'fromBlock': start_block,
        'toBlock': end_block,
        'topics': [MESSAGE_SENT_EVENT]
    })
    
    for log in logs:
        try:
            block = await w3_eth.eth.get_block(log['blockNumber'])
            tx = await w3_eth.eth.get_transaction(log['transactionHash'])
            tx_analysis = await analyze_transaction_type(w3_eth, log['transactionHash'], CIRCLE_TOKEN_MESSENGER)
            
            nonce = int(log['topics'][1].hex(), 16)
            topic2_hex = log['topics'][2].hex()
            burn_token = AsyncWeb3.to_checksum_address('0x' + topic2_hex[-40:])
            
            decimals, symbol = await get_token_info(w3_eth, burn_token)
            
            raw_data = log['data']
            amount = decode_uint256(raw_data[0:32])
            mint_recipient = decode_address(raw_data[32:64])
            destination_domain = decode_uint256(raw_data[64:96])
            destination_chain = DOMAIN_TO_CHAIN.get(destination_domain, f"Unknown ({destination_domain})")
            
            with open(output_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    nonce,
                    log['blockNumber'],
                    log['transactionHash'].hex(),
                    datetime.utcfromtimestamp(block['timestamp']).strftime('%Y-%m-%d %H:%M:%S'),
                    tx['from'],
                    tx_analysis['is_direct'],
                    tx_analysis['total_logs'],
                    tx_analysis['target_positions'][0] + 1 if tx_analysis['target_positions'] else None,
                    tx_analysis['first_contract'],
                    burn_token,
                    symbol,
                    amount / (10 ** decimals),
                    mint_recipient,
                    destination_chain
                ])
            
            print(f"Processed transfer #{nonce} in block {log['blockNumber']}")
            
        except Exception as e:
            print(f"Error processing log: {str(e)}")
            continue

async def main():
    end_block = await w3_eth.eth.block_number
    start_block = end_block - 1000  # Last 1000 blocks
    await get_cctp_transfers(start_block, end_block, 'base_transfers_out.csv')

if __name__ == "__main__":
    asyncio.run(main())
