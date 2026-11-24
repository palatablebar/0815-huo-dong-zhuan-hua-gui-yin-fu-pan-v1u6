EXPECTED = {
    "0001": (2, 90, "READY"),
    "0002": (1, 31, "READY"),
    "0003": (0, None, "NO_TOUCH"),
    "0004": (2, 41, "MISMATCH"),
}
EVIDENCE = {
    "0001": {"channel": 2, "chosen_touch": "000104", "elapsed_min": 15},
    "0002": {"channel": 3, "chosen_touch": "000202", "elapsed_min": 30},
}
