import collections
import random
import math

from common.network_helpers import get_stochastic_network_move

def _monte_carlo_sample(game_spec, board_state, side, policy = False, session = None, input_layer = None,
                        output_layer = None, valid_only = False, cnn_on = False):
    """Sample a single rollout from the current board_state and side. Moves are made to the current board_state until we
     reach a terminal state then the result and the first move made to get there is returned.

    Args:
        game_spec (BaseGameSpec): The specification for the game we are evaluating
        board_state (3x3 tuple of int): state of the board
        side (int): side currently to play. +1 for the plus player, -1 for the minus player

    Returns:
        (result(int), move(int,int)): The result from this rollout, +1 for a win for the plus player -1 for a win for
            the minus player, 0 for a draw
    """
    result = game_spec.has_winner(board_state)
    if result != None:
        return result, None

    moves = list(game_spec.available_moves(board_state))
    if not moves:
        return 0, None

    # select a random move
    if policy:
        # get stochastic network move gives wrong type (array of 81 elements instead of tuple), so we need to reconfigure
        move = get_stochastic_network_move(session, input_layer, output_layer, board_state, side,
                                            valid_only, game_spec, cnn_on)
        move = game_spec.flat_move_to_tuple([i for i,x in enumerate(move) if x == 1][0])
    else:
        move = random.choice(moves)
    result, next_move = _monte_carlo_sample(game_spec, game_spec.apply_move(board_state, move, side), -side, policy,
                                            session, input_layer, output_layer, valid_only, cnn_on)
    return result, move


def monte_carlo_tree_search(game_spec, board_state, side, number_of_samples, session = None,
                            input_layer = None, output_layer = None, valid_only = False, cnn_on = False, policy = False):
    """Evaluate the best from the current board_state for the given side using monte carlo sampling.

    Args:
        game_spec (BaseGameSpec): The specification for the game we are evaluating
        board_state (3x3 tuple of int): state of the board
        side (int): side currently to play. +1 for the plus player, -1 for the minus player
        number_of_samples (int): number of samples rollouts to run from the current position, the higher the number the
            better the estimation of the position

    Returns:
        (result(int), move(int,int)): The average result for the best move from this position and what that move was.
    """
    move_wins = collections.defaultdict(int)
    move_samples = collections.defaultdict(int)
    for _ in range(number_of_samples):
        result, move = _monte_carlo_sample(game_spec, board_state, side, policy, session, input_layer,
                        output_layer, valid_only, cnn_on)
        # store the result and a count of the number of times we have tried this move
        if result == side:
            move_wins[move] += 1
        move_samples[move] += 1
    # get the move with the best average result
    # if all samples lost, move_wins is empty, choose least sampled move
    if len(move_wins)==0:
        move = min(move_samples, key=move_samples.get)
    else:
        move = max(move_wins, key=lambda x: move_wins.get(x) / move_samples[move])
    if policy:
        # When a policy is used, we want to return a list of length 81 since this is used for the minibatch moves
        listofzeros = [0] * 81
        flat_move = game_spec.tuple_move_to_flat(move)
        listofzeros[flat_move] = 1
    return move_wins[move] / move_samples[move], move if not policy else listofzeros


def _upper_confidence_bounds(payout, samples_for_this_machine, log_total_samples):
    return payout / samples_for_this_machine + math.sqrt((2 * log_total_samples) / samples_for_this_machine)


def monte_carlo_tree_search_uct(game_spec, board_state, side, number_of_samples):
    """Evaluate the best from the current board_state for the given side using monte carlo sampling with upper
    confidence bounds for trees.

    Args:
        game_spec (BaseGameSpec): The specification for the game we are evaluating
        board_state (3x3 tuple of int): state of the board
        side (int): side currently to play. +1 for the plus player, -1 for the minus player
        number_of_samples (int): number of samples rollouts to run from the current position, the higher the number the
            better the estimation of the position

    Returns:
        (result(int), move(int,int)): The average result for the best move from this position and what that move was.
    """
    state_results = collections.defaultdict(float)
    state_samples = collections.defaultdict(float)

    for _ in range(number_of_samples):
        current_side = side
        current_board_state = board_state
        first_unvisited_node = True
        rollout_path = []
        result = None

        while result == None:
            move_states = {move: game_spec.apply_move(current_board_state, move, current_side)
                           for move in game_spec.available_moves(current_board_state)}

            if not move_states:
                result = 0
                break

            if all((state in state_samples) for _, state in move_states):
                log_total_samples = math.log(sum(state_samples[s] for s in move_states.values()))
                move, state = max(move_states, key=lambda _, s: _upper_confidence_bounds(state_results[s],
                                                                                         state_samples[s],
                                                                                         log_total_samples))
            else:
                move = random.choice(list(move_states.keys()))

            current_board_state = move_states[move]

            if first_unvisited_node:
                rollout_path.append((current_board_state, current_side))
                if current_board_state not in state_samples:
                    first_unvisited_node = False

            current_side = -current_side

            result = game_spec.has_winner(current_board_state)

        for path_board_state, path_side in rollout_path:
            state_samples[path_board_state] += 1.
            result *= path_side
            # normalize results to be between 0 and 1 before this it between -1 and 1
            result /= 2.
            result += .5
            state_results[path_board_state] += result

    move_states = {move: game_spec.apply_move(board_state, move, side) for move in game_spec.available_moves(board_state)}

    # If a certain state is not sampled by MCTS, state_results is divided by 10e3 to make sure this is not chosen.
    move = max(move_states, key=lambda x: state_results[move_states[x]] / (state_samples[move_states[x]] if state_samples[move_states[x]] > 0 else 10e3))

    return state_results[move_states[move]] / state_samples[move_states[move]], move

if __name__ == '__main__':
    from games.tic_tac_toe import TicTacToeGameSpec

    sample_board_state = ((1, 0, -1),
                          (1, 0, 0),
                          (0, -1, 0))

    print(monte_carlo_tree_search_uct(TicTacToeGameSpec(), sample_board_state, -1, 10000))
