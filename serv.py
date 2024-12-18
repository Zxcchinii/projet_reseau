import asyncio
import json
import random
import uuid
import logging
from typing import Dict, List

import websockets
from websockets.server import WebSocketServerProtocol

class Connect4Game:
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.board = [[0 for _ in range(7)] for _ in range(6)]
        self.current_player = 1
        self.players: Dict[int, str] = {}  # {player_number: player_id}
        self.game_over = False
        self.winner = None
        self.max_players = 2

    def check_winner(self, player):
        # Horizontal check
        for row in range(6):
            for col in range(4):
                if all(self.board[row][col+i] == player for i in range(4)):
                    return True
        
        # Vertical check
        for col in range(7):
            for row in range(3):
                if all(self.board[row+i][col] == player for i in range(4)):
                    return True
        
        # Diagonal checks
        for row in range(3):
            for col in range(4):
                # Diagonal down-right
                if all(self.board[row+i][col+i] == player for i in range(4)):
                    return True
                # Diagonal down-left
                if all(self.board[row+i][col+3-i] == player for i in range(4)):
                    return True
        
        return False

    def make_move(self, player, column):
        # Validate column
        if column < 0 or column >= 7:
            return False, "Invalid column"
        
        # Find first empty row in the column
        for row in range(5, -1, -1):
            if self.board[row][column] == 0:
                self.board[row][column] = player
                
                # Check for winner
                if self.check_winner(player):
                    self.game_over = True
                    self.winner = player
                
                # Switch player
                self.current_player = 3 - player
                return True, "Move successful"
        
        return False, "Column is full"

class Connect4Server:
    def __init__(self):
        self.games: Dict[str, Connect4Game] = {}
        self.player_connections: Dict[str, WebSocketServerProtocol] = {}
        self.game_waiting = None
        self.logger = logging.getLogger('Connect4Server')
        logging.basicConfig(level=logging.INFO)

    async def register_player(self, websocket: WebSocketServerProtocol):
        # Generate unique player ID
        player_id = str(uuid.uuid4())
        self.player_connections[player_id] = websocket
        
        # Check if there's a waiting game or create a new one
        if not self.game_waiting:
            # Create a new game and wait for another player
            game_id = str(uuid.uuid4())
            game = Connect4Game(game_id)
            self.games[game_id] = game
            self.game_waiting = game
            
            # Assign first player
            game.players[1] = player_id
            
            await websocket.send(json.dumps({
                'type': 'game_status',
                'status': 'waiting',
                'player_number': 1,
                'game_id': game_id
            }))
            self.logger.info(f"Player {player_id} created game {game_id}")
        else:
            # Join existing waiting game
            game = self.game_waiting
            game.players[2] = player_id
            
            # Notify both players that the game is starting
            for player_number, p_id in game.players.items():
                player_socket = self.player_connections[p_id]
                await player_socket.send(json.dumps({
                    'type': 'game_status',
                    'status': 'started',
                    'player_number': player_number,
                    'game_id': game.game_id
                }))
            
            # Reset waiting game
            self.game_waiting = None
            self.logger.info(f"Game {game.game_id} started with two players")

        return player_id

    async def handle_move(self, player_id, data):
        # Find the game the player is in
        for game in self.games.values():
            if player_id in game.players.values():
                # Determine player number
                player_number = list(game.players.keys())[list(game.players.values()).index(player_id)]
                
                # Validate it's the player's turn
                if game.current_player != player_number:
                    return {'success': False, 'message': 'Not your turn'}
                
                # Make the move
                success, message = game.make_move(player_number, data['column'])
                
                if success:
                    # Broadcast updated game state to both players
                    for p_number, p_id in game.players.items():
                        player_socket = self.player_connections[p_id]
                        await player_socket.send(json.dumps({
                            'type': 'game_update',
                            'board': game.board,
                            'current_player': game.current_player,
                            'game_over': game.game_over,
                            'winner': game.winner
                        }))
                
                return {
                    'success': success, 
                    'message': message,
                    'board': game.board,
                    'current_player': game.current_player,
                    'game_over': game.game_over,
                    'winner': game.winner
                }
        
        return {'success': False, 'message': 'Game not found'}

    async def handle_websocket(self, websocket: WebSocketServerProtocol, path):
        try:
            # Register player
            player_id = await self.register_player(websocket)
            
            # Handle incoming messages
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if data['type'] == 'move':
                        response = await self.handle_move(player_id, data)
                        await websocket.send(json.dumps(response))
                
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
        
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"Player {player_id} disconnected")
            # TODO: Implement game cleanup for disconnected players
        
        finally:
            # Remove player connection
            if player_id in self.player_connections:
                del self.player_connections[player_id]

    async def start_server(self):
        server = await websockets.serve(
            self.handle_websocket, 
            "0.0.0.0", 5000
        )
        self.logger.info("Multiplayer Connect Four Server started")
        await server.wait_closed()

# Run the server
if __name__ == "__main__":
    game_server = Connect4Server()
    asyncio.run(game_server.start_server())