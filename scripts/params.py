kp = -2*10**18
ki = -1*10**17
co_bias = 10**18
output_upper_bound = 10*10**18
output_lower_bound = 10**15 # 1e-3
target_time_since = 1800 * 10**18
default_window_size = 10

# reward calc
tip_reward_type = 322 # 90th maxPf
min_reward = 10**18 # 1
max_reward = 10**22 # 10,000
min_ts = 10**18 #11
max_ts = 72 * 10**20 #7200
min_deviation = 10**17 # 0.1
max_deviation = 3 * 10**18 # 3
coeff = [49151612841, 162468714000847667200, 96430657017234, 503653013402573209600]
min_fee = 0

scales = {(2, 42161): 359179550584, # arb
 (2, 10): 6889789, # op
 (2, 8453): 9306238, # base
 (2, 59144): 264213942, # linea
 (2, 1868): 1541801, # soneium
 (2, 130): 50533290, # unichain
 (2, 1): 8107471175} # eth
