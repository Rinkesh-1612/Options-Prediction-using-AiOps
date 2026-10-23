"""Trading-session clock constants. No heavy imports: the serving containers use this too.

Time convention (single place it is defined):
  ts_ns is UTC epoch nanoseconds. IST = UTC + 5:30 (India has no DST), so the IST calendar day and
  minute are computed by plain arithmetic -- no timezone database, no Spark session-timezone surprises.
    sod         seconds since IST midnight
    minute      minutes since IST midnight; 09:15 -> 555, 15:29 -> 929
  A tick at 09:15:59.9 belongs to minute 555. "State at minute m" means the last tick with
  minute == m, i.e. the market as it stood at the END of m.
"""

IST_OFFSET_S = 19800  # 5h30m
SESSION_FIRST_MIN = 9 * 60 + 15  # 555 = 09:15
SESSION_LAST_MIN = 15 * 60 + 29  # 929 = 15:29 (minute bar ending 15:30)
SESSION_MINUTES = SESSION_LAST_MIN - SESSION_FIRST_MIN + 1  # 375
