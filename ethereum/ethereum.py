import asyncio
from web3 import AsyncWeb3
from datetime import datetime

w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider('https://eth-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR'))
CIRCLE_TOKEN_MESSENGER = AsyncWeb3.to_checksum_address('0xBd3fa81B58Ba92a82136038B25aDec7066af3155')
MESSAGE_SENT_EVENT = '0x2fa9ca894982930190727e75500a97d8dc500233a5065e0f3126c48fbe0343c0'

ERC20_ABI = [
    {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}
]

async def get_token_info(token_address):
    token_contract = w3.eth.contract(address=token_address, abi=ERC20_ABI)
    decimals = await token_contract.functions.decimals().call()
    symbol = await token_contract.functions.symbol().call()
    return decimals, symbol

def decode_uint256(hex_data):
    return int.from_bytes(hex_data, byteorder='big')

def decode_address(hex_data):
    raw_address = '0x' + hex_data[-20:].hex()
    return AsyncWeb3.to_checksum_address(raw_address)

async def analyze_transaction_type(tx_hash):
    receipt = await w3.eth.get_transaction_receipt(tx_hash)
    tx = await w3.eth.get_transaction(tx_hash)
    
    # Check if direct interaction with CCTP
    is_direct = tx['to'].lower() == CIRCLE_TOKEN_MESSENGER.lower()
    
    # Count total logs to determine complexity
    total_logs = len(receipt['logs'])
    cctp_logs = sum(1 for log in receipt['logs'] if log['address'].lower() == CIRCLE_TOKEN_MESSENGER.lower())
    
    # Check position of CCTP log
    cctp_positions = [i for i, log in enumerate(receipt['logs']) if log['address'].lower() == CIRCLE_TOKEN_MESSENGER.lower()]
    
    return {
        'is_direct': is_direct,
        'total_logs': total_logs,
        'cctp_log_count': cctp_logs,
        'cctp_positions': cctp_positions,
        'first_contract': receipt['logs'][0]['address'] if receipt['logs'] else None
    }

async def get_cctp_transfers(start_block, end_block):
    logs = await w3.eth.get_logs({
        'address': CIRCLE_TOKEN_MESSENGER,
        'fromBlock': start_block,
        'toBlock': end_block,
        'topics': [MESSAGE_SENT_EVENT]
    })
    
    for log in logs:
        block = await w3.eth.get_block(log['blockNumber'])
        tx = await w3.eth.get_transaction(log['transactionHash'])
        tx_analysis = await analyze_transaction_type(log['transactionHash'])
        
        nonce = int(log['topics'][1].hex(), 16)
        burn_token = decode_address(log['topics'][2])
        decimals, symbol = await get_token_info(burn_token)
        
        raw_data = log['data']
        amount = decode_uint256(raw_data[0:32])
        mint_recipient = decode_address(raw_data[32:64])
        destination_domain = decode_uint256(raw_data[64:96])
        destination_token_messenger = decode_address(raw_data[96:128])
        
        print(f'\nCCTP Transfer found in block {log["blockNumber"]}')
        print(f'Transaction hash: {log["transactionHash"].hex()}')
        print(f'Block time: {datetime.utcfromtimestamp(block["timestamp"]).strftime("%Y-%m-%d %H:%M:%S UTC")}')
        print(f'Origin: {tx["from"]}')
        print(f'Transfer Type: {"Direct CCTP" if tx_analysis["is_direct"] else "Part of Larger Transaction"}')
        print(f'Transaction Complexity: {tx_analysis["total_logs"]} total events')
        if not tx_analysis["is_direct"]:
            print(f'First Contract: {tx_analysis["first_contract"]}')
            print(f'CCTP Position: {tx_analysis["cctp_positions"][0] + 1} of {tx_analysis["total_logs"]} events')
        print(f'Nonce: {nonce}')
        print(f'Token: {symbol} ({burn_token})')
        print(f'Amount: {amount / (10 ** decimals):,.2f} {symbol}')
        print(f'To: {mint_recipient}')
        print(f'Destination Domain: {destination_domain}')
        print(f'Destination Token Messenger: {destination_token_messenger}')
        print('-' * 50)

async def main():
    end_block = await w3.eth.block_number
    start_block = end_block - 100
    await get_cctp_transfers(start_block, end_block)

if __name__ == "__main__":
    asyncio.run(main())