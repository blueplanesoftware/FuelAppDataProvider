from typing import List

def get_plate_codes() -> List[str]:
	"""Return TR plate codes as zero-padded strings: 01..81."""
	return [f"{i:02d}" for i in range(1, 82)]


