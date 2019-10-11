import time


def fix_heartbeat_manager(fix_trader):
	"""
	Simple function that sends a heartbeat message to GDAX if no message has
	been sent recently. This is necessary because GDAX requires some sort of
	message at least once every 30 seconds or else it closes the FIX connection.

	Parameters:
		fix_trader: FIXTrader
			Used to send heartbeat requests.

	Returns:
		None
	"""
	while True:
		if (time.time() - fix_trader.last_send_msg_time) > 20:
			fix_trader.request('heartbeat')
		time.sleep(1)
