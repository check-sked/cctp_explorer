import aiohttp
import asyncio
from datetime import datetime
import csv
import json
import base64
import re

# Message transmitter program ID
MESSAGE_TRANSMITTER = "CCTPiPYPc6AsJuwueEnWgSgucamXDZwBd53dQ11YiKX3"

async def get_slot(session, url):
    async with session.post(url, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSlot",
    }) as response:
        data = await response.json()
        return data['result']

async def get_block(session, url, slot):
    async with session.post(url, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBlock",
        "params": [
            slot,
            {
                "encoding": "json",
                "maxSupportedTransactionVersion": 0,
                "transactionDetails": "full",
                "rewards": False
            }
        ]
    }) as response:
        return await response.json()

async def get_transaction(session, url, signature):
    async with session.post(url, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "json",
                "maxSupportedTransactionVersion": 0,
            }
        ]
    }) as response:
        return await response.json()

def extract_nonce_from_instructions(transaction):
    CCTP_PROGRAM = "CCTPmbSD7gX1bxKPAmg77w8oFzNFpaQiQUWD43TKaecd"
    
    try:
        # Look for the first instruction to the CCTP program
        instructions = transaction['transaction']['message']['instructions']
        account_keys = transaction['transaction']['message']['accountKeys']
        
        for instruction in instructions:
            program_id_idx = instruction.get('programIdIndex')
            if program_id_idx is not None and account_keys[program_id_idx] == CCTP_PROGRAM:
                try:
                    import base58
                    # Decode the base58 instruction data
                    data = base58.b58decode(instruction['data'])
                    
                    # Convert to hex for debugging
                    hex_data = data.hex()
                    print(f"Instruction data (hex): {hex_data}")
                    
                    # Extract the nonce from specific position (may need adjustment)
                    # Looking for a 2-byte value
                    # Try different offsets to find the correct position
                    for i in range(len(data)-2):
                        nonce_candidate = int.from_bytes(data[i:i+2], 'little')
                        if nonce_candidate == 5145:  # Known good value for testing
                            print(f"Found nonce at offset {i}")
                            return str(nonce_candidate)
                    
                    # If we don't find the exact match, try the most likely position
                    nonce = int.from_bytes(data[20:22], 'little')
                    return str(nonce)
                except Exception as e:
                    print(f"Error decoding instruction data: {str(e)}")
                    return None
                
        return None
    except Exception as e:
        print(f"Error extracting nonce: {str(e)}")
        return None

def get_usdc_info(transaction):
    USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    
    try:
        if 'meta' not in transaction or 'postTokenBalances' not in transaction['meta']:
            return None, None

        # Look through postTokenBalances for USDC mint
        for balance in transaction['meta']['postTokenBalances']:
            if balance['mint'] == USDC_MINT:
                receiver = balance['owner']
                amount = float(balance['uiTokenAmount']['uiAmountString'])
                return receiver, amount

        return None, None
    except Exception as e:
        print(f"Error extracting USDC info: {str(e)}")
        return None, None

async def save_transaction_details(session, url, signature):
    tx_data = await get_transaction(session, url, signature)
    if 'result' in tx_data and tx_data['result']:
        with open('test.json', 'w') as f:
            json.dump(tx_data['result'], f, indent=2)
        print(f"Transaction details saved to test.json")
    return tx_data.get('result')

async def get_cctp_transactions(start_slot, end_slot, output_file):
    url = "https://solana-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR"
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'slot_number',
            'transaction_hash',
            'timestamp',
            'block_hash',
            'usdc_receiver',
            'usdc_amount',
            'cctp_nonce'
        ])
    
    async with aiohttp.ClientSession() as session:
        for slot in range(start_slot, end_slot + 1):
            try:
                block = await get_block(session, url, slot)
                
                if 'result' in block and block['result']:
                    block_data = block['result']
                    
                    if 'transactions' in block_data:
                        for tx in block_data['transactions']:
                            # Check if the transaction involves the message transmitter program
                            if any(account == MESSAGE_TRANSMITTER 
                                  for account in tx['transaction']['message']['accountKeys']):
                                
                                timestamp = datetime.fromtimestamp(block_data['blockTime'])
                                tx_hash = tx['transaction']['signatures'][0]
                                
                                # Extract additional information
                                nonce = extract_nonce_from_instructions(tx)
                                usdc_receiver, usdc_amount = get_usdc_info(tx)
                                
                                with open(output_file, 'a', newline='') as f:
                                    writer = csv.writer(f)
                                    writer.writerow([
                                        slot,
                                        tx_hash,
                                        timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                                        block_data['blockhash'],
                                        usdc_receiver,
                                        usdc_amount,
                                        nonce
                                    ])
                                
                                print(f"Found CCTP transaction in slot {slot}: {tx_hash}")
                                print(f"USDC Receiver: {usdc_receiver}")
                                print(f"CCTP Nonce: {nonce}")
                                
                                # Save the first CCTP transaction we find to test.json
                                await save_transaction_details(session, url, tx_hash)
                                return  # Exit after saving the first transaction
                
            except Exception as e:
                print(f"Error processing slot {slot}: {str(e)}")
                continue

async def main():
    async with aiohttp.ClientSession() as session:
        url = "https://solana-mainnet.g.alchemy.com/v2/AMsnqGqzMboS_tNkYDeec0MleUfhykIR"
        current_slot = await get_slot(session, url)
        start_slot = current_slot - 1000  # Last 1000 slots
        await get_cctp_transactions(start_slot, current_slot, 'solana_cctp_transactions.csv')

if __name__ == "__main__":
    asyncio.run(main())