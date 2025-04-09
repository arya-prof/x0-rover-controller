import asyncio
import websockets
import json
import random

clients = set()

async def handle_connection(websocket):
    print("Client connected")
    clients.add(websocket)
    try:
        async for message in websocket:
            print(f"Received from GUI: {message}")
            # Simulate a response (telemetry)
            response = {
                "battery": random.randint(50, 100),
                "imu": {"pitch": round(random.uniform(-5, 5), 2), "roll": round(random.uniform(-5, 5), 2)},
                "temp": round(random.uniform(20, 30), 1),
                "arm": {"joint1": random.randint(0, 180)}
            }
            await websocket.send(json.dumps(response))
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    finally:
        clients.remove(websocket)

async def main():
    async with websockets.serve(handle_connection, "localhost", 8765):
        print("Mock Rover Server running at ws://localhost:8765")
        await asyncio.Future()  # run forever

asyncio.run(main())
