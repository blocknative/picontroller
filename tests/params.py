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


scales = {(2, 42161): 99340000000000000//10**9, # Arbitrum
          (2,8453): 144939290000000000//10**9, # Base
          (2,59144): 612710000000000000//10**9, # Linea
          (2,10): 228550000000000//10**9, # Opt
          (2,1868): 228550000000000//10**9, # Soneium TODO: UPDATE
          (2,130): 228550000000000//10**9, # Unichain TODO: UPDATE
          (2,1): 10**9 #ethereum TODO: update
          }
