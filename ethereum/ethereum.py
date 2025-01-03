import asyncio
from web3 import AsyncWeb3
from web3.middleware import async_geth_poa_middleware
from datetime import datetime

def setup_web3_provider(url):
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url))
    w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
    return w3

w3_eth = setup_web3_provider('https://eth-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')
w3_base = setup_web3_provider('https://base-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')
w3_op = setup_web3_provider('https://opt-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')
w3_poly = setup_web3_provider('https://polygon-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')
w3_arb = setup_web3_provider('https://arb-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')
w3_avax = setup_web3_provider('https://avax-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR')

CIRCLE_TOKEN_MESSENGER = AsyncWeb3.to_checksum_address('0xBd3fa81B58Ba92a82136038B25aDec7066af3155')
MESSAGE_TRANSMITTERS = {
    'ethereum': '0x0a992d191deec32afe36203ad87d7d289a738f81',
    'avalanche': '0x8186359af5f57fbb40c6b14a588d2a59c0c29880',
    'optimism': '0x4d41f22c5a0e5c74090899e5a8fb597a8842b3e8',
    'arbitrum': '0xC30362313FBBA5cf9163F0bb16a0e01f01A896ca',
    'base': '0xAD09780d193884d503182aD4588450C416D6F9D4',
    'polygon': '0xF3be9355363857F3e001be68856A2f96b4C39Ba9'
}

DOMAIN_TO_CHAIN = {
    0: 'ethereum',
    1: 'avalanche',
    2: 'optimism',
    3: 'arbitrum',
    4: 'solana',
    5: 'sui',
    6: 'base',
    7: 'polygon'
}

CHAIN_TO_W3 = {
    'ethereum': w3_eth,
    'base': w3_base,
    'optimism': w3_op,
    'polygon': w3_poly,
    'arbitrum': w3_arb,
    'avalanche': w3_avax
}

MESSAGE_SENT_EVENT = '0x2fa9ca894982930190727e75500a97d8dc500233a5065e0f3126c48fbe0343c0'
MESSAGE_RECEIVED_EVENT = '0x58200b4c34ae05ee816d710053fff3fb75af4395915d3d2a771b24aa10e3cc5d'

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
    raw_address = '0x' + hex_data[-20:].hex()
    return AsyncWeb3.to_checksum_address(raw_address)

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

def decode_message_body(message_body):
    if isinstance(message_body, str):
        hex_str = message_body[message_body.find('000000000000000000000000'):]
    else:
        hex_data = message_body.hex()
        hex_str = hex_data[hex_data.find('000000000000000000000000'):]
    
    token = decode_address(bytes.fromhex(hex_str[0:64]))
    recipient = decode_address(bytes.fromhex(hex_str[64:128]))
    amount = int(hex_str[128:192], 16)
    return token, recipient, amount

async def find_matching_logs(w3, chain_name, transmitter, nonce, start_block, end_block):
    try:
        filter_params = {
            'address': transmitter,
            'fromBlock': start_block,
            'toBlock': end_block,
            'topics': [
                AsyncWeb3.to_hex(hexstr=MESSAGE_RECEIVED_EVENT),
                None,
                AsyncWeb3.to_hex(hexstr='0x' + hex(nonce)[2:].zfill(64))
            ]
        }
        logs = await w3.eth.get_logs(filter_params)
        return logs
    except Exception as e:
        print(f"Error querying {chain_name}: {str(e)}")
        return []

async def find_destination_tx(destination_chain, nonce, source_block_time):
    if destination_chain not in CHAIN_TO_W3:
        return None
        
    w3 = CHAIN_TO_W3[destination_chain]
    transmitter = AsyncWeb3.to_checksum_address(MESSAGE_TRANSMITTERS[destination_chain])
    
    try:
        current_block = await w3.eth.block_number
        block_lookback = {
            'base': 50000,
            'arbitrum': 100000,
            'optimism': 50000,
            'polygon': 25000,
            'avalanche': 25000
        }.get(destination_chain, 25000)
        
        estimated_block = current_block - block_lookback
        
        for chunk_start in range(estimated_block, current_block + 1, 2000):
            chunk_end = min(chunk_start + 2000, current_block)
            logs = await find_matching_logs(w3, destination_chain.upper(), transmitter, nonce, chunk_start, chunk_end)
            
            if logs:
                print(f"Match found in block {logs[0]['blockNumber']}")
                return logs[0]
                
    except Exception as e:
        print(f"Chain error for {destination_chain}: {str(e)}")
    
    return None

async def get_cctp_transfers(start_block, end_block):
    logs = await w3_eth.eth.get_logs({
        'address': CIRCLE_TOKEN_MESSENGER,
        'fromBlock': start_block,
        'toBlock': end_block,
        'topics': [MESSAGE_SENT_EVENT]
    })
    
    for log in logs:
        block = await w3_eth.eth.get_block(log['blockNumber'])
        tx = await w3_eth.eth.get_transaction(log['transactionHash'])
        tx_analysis = await analyze_transaction_type(w3_eth, log['transactionHash'], CIRCLE_TOKEN_MESSENGER)
        
        nonce = int(log['topics'][1].hex(), 16)
        burn_token = decode_address(log['topics'][2])
        decimals, symbol = await get_token_info(w3_eth, burn_token)
        
        raw_data = log['data']
        amount = decode_uint256(raw_data[0:32])
        mint_recipient = decode_address(raw_data[32:64])
        destination_domain = decode_uint256(raw_data[64:96])
        destination_chain = DOMAIN_TO_CHAIN.get(destination_domain)
        
        print(f'\nCCTP Transfer #{nonce}')
        print('-' * 50)
        print('SOURCE (Ethereum)')
        print(f'Block: {log["blockNumber"]}')
        print(f'Transaction hash: {log["transactionHash"].hex()}')
        print(f'Block time: {datetime.utcfromtimestamp(block["timestamp"]).strftime("%Y-%m-%d %H:%M:%S UTC")}')
        print(f'Origin: {tx["from"]}')
        print(f'Transfer Type: {"Direct CCTP" if tx_analysis["is_direct"] else "Part of Larger Transaction"}')
        if not tx_analysis["is_direct"]:
            print(f'Transaction Complexity: {tx_analysis["total_logs"]} total events')
            print(f'First Contract: {tx_analysis["first_contract"]}')
            print(f'CCTP Position: {tx_analysis["target_positions"][0] + 1} of {tx_analysis["total_logs"]} events')
        print(f'Token: {symbol} ({burn_token})')
        print(f'Amount: {amount / (10 ** decimals):,.2f} {symbol}')
        print(f'To: {mint_recipient}')
        print(f'Destination Chain: {destination_chain.title() if destination_chain in CHAIN_TO_W3 else f"Unsupported ({destination_domain})"}')
        
        if destination_chain in CHAIN_TO_W3:
            source_time = datetime.utcfromtimestamp(block["timestamp"])
            dest_tx = await find_destination_tx(destination_chain, nonce, source_time)
            if dest_tx:
                dest_block = await CHAIN_TO_W3[destination_chain].eth.get_block(dest_tx['blockNumber'])
                dest_tx_full = await CHAIN_TO_W3[destination_chain].eth.get_transaction(dest_tx['transactionHash'])
                dest_analysis = await analyze_transaction_type(CHAIN_TO_W3[destination_chain], dest_tx['transactionHash'], MESSAGE_TRANSMITTERS[destination_chain])
                
                token, recipient, _ = decode_message_body(dest_tx['data'])
                
                print(f'\nDESTINATION ({destination_chain.title()})')
                print(f'Block: {dest_tx["blockNumber"]}')
                print(f'Transaction hash: {dest_tx["transactionHash"].hex()}')
                print(f'Block time: {datetime.utcfromtimestamp(dest_block["timestamp"]).strftime("%Y-%m-%d %H:%M:%S UTC")}')
                print(f'Receiver: {dest_tx_full["from"]}')
                print(f'Transfer Type: {"Direct CCTP" if dest_analysis["is_direct"] else "Part of Larger Transaction"}')
                if not dest_analysis["is_direct"]:
                    print(f'Transaction Complexity: {dest_analysis["total_logs"]} total events')
                    print(f'First Contract: {dest_analysis["first_contract"]}')
                    print(f'CCTP Position: {dest_analysis["target_positions"][0] + 1} of {dest_analysis["total_logs"]} events')
                print(f'Token: {symbol} (Native {destination_chain.title()} {symbol})')
                print(f'Amount: {amount / (10 ** decimals):,.2f} {symbol}')
                print(f'Final Recipient: {recipient}')
            else:
                print('\nDestination transaction not found')
        
        print('-' * 50)

async def main():
    end_block = await w3_eth.eth.block_number
    start_block = end_block - 1000
    await get_cctp_transfers(start_block, end_block)

if __name__ == "__main__":
    asyncio.run(main())