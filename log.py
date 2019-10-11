import datetime as dt
import logging
import queue
import time


class Log:

	def __init__(self):
		"""
		Simple logger that maintains a queue of strings to eventually print out
		to log file. This is done because constantly opening and writing to a
		file every time something should be logged is slow - if the flush()
		method is called only when not in the so called "hot path," the overall
		program will have much lower latency in places where microseconds matter.
		"""

		self.setup_logger()
		self.log = logging.info
		self.queue = queue.Queue()

	def setup_logger(self):
		"""
		Simple setup procedure for setting up and naming a log file.

		Returns:
			None
		"""

		current_time_str = dt.datetime.now().strftime('%m-%d-%Y %Hh %Mm %Ss')
		logging.basicConfig(
			filename=f'GDAX Log {current_time_str}.log',
			level=logging.DEBUG
		)
		# Suppress url request debug statements from log file, it's mostly
		# unnecessary clutter
		logging.getLogger("requests").setLevel(logging.WARNING)

	def add(self, message):
		"""
		Inserts a message at the end of the log queue.

		Parameters:
			message: variable type
				Message to log. Can be of any type that has a string
				representation.

		Returns:
			None
		"""

		current_time_str = str(time.perf_counter())
		self.queue.put(f'[{current_time_str}] {message}')

	def flush(self):
		"""
		Outputs all messages in the queue to the log file.

		Returns:
			None
		"""
		while not self.queue.empty():
			self.log(self.queue.get())
