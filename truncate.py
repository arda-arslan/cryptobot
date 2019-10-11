def truncate(num, places):
	"""
	Truncates/pads a float to the passed number of decimal places without
	rounding up. This is important for formatting order size correctly when
	sending orders to GDAX.

	Parameters:
		num: float
			The number to truncate.
		places: float
			The number of decimal places to truncate to.

	Returns:
		truncated: float
			Input num truncated to input places number of decimal places.
	"""
	s = f'{num}'
	if 'e' in s or 'E' in s:
		return float('{0:.{1}f}'.format(num, places))
	i, p, d = s.partition('.')
	truncated = float('.'.join([i, (d + '0' * places)[:places]]))
	return truncated
