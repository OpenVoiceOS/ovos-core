# Binary Classifier

labels: OCP, other

| pipeline                   | language | accuracy           | params                                                                                                                                               | size (MB) |
|----------------------------|----------|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| binary_ocp_cv2_kw_medium * | en       | 0.9931496867494176 | {'penalty': None, 'l1_ratio': 0.15, 'early_stopping': False, 'alpha': 0.07}                                                                          | 0.01      |
| binary_ocp_cv2_small       | en       | 0.9888979130544839 | {'penalty': None, 'l1_ratio': 0.9, 'early_stopping': False, 'alpha': 0.005}                                                                          | 2.166     |
| binary_ocp_kw_small        | all      | 0.9326234280627232 | {'solver': 'adam', 'learning_rate': 'invscaling', 'hidden_layer_sizes': (120, 20, 80), 'early_stopping': True, 'alpha': 0.006, 'activation': 'tanh'} | 2.373     |
| binary_ocp_kw_tiny         | all      | 0.8919135638508334 | {'penalty': None, 'l1_ratio': 0.7, 'early_stopping': True, 'alpha': 0.02}                                                                            | 0.01      |

`*` requires `binary_ocp_cv2_small`

# Playback Classifier

labels: audio, video, external

| pipeline                     | language | accuracy           | params                                                                                                                                                  | size (MB) |
|------------------------------|----------|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| playback_ocp_cv2_kw_medium * | en       | 0.9491247659281933 | {'penalty': None, 'l1_ratio': 0.5, 'early_stopping': False, 'alpha': 0.07}                                                                              | 0.021     |
| playback_ocp_kw_small        | all      | 0.9017183438359262 | {'solver': 'adam', 'learning_rate': 'invscaling', 'hidden_layer_sizes': (114, 101, 36), 'early_stopping': False, 'alpha': 0.0485, 'activation': 'tanh'} | 3.904     |
| playback_ocp_kw_tiny         | all      | 0.8325265234776467 | {'penalty': None, 'l1_ratio': 0.9, 'early_stopping': False, 'alpha': 0.0001}                                                                            | 0.021     |

`*` requires `playback_ocp_cv2_small`

# Media Classifier

labels: movie, music, audiobook, podcast ....

| pipeline                  | language | accuracy           | params                                                                                                                                         | size (MB) |
|---------------------------|----------|--------------------|------------------------------------------------------------------------------------------------------------------------------------------------|-----------|
| media_ocp_cv2_kw_medium * | en       | 0.9054523222627585 | {'penalty': None, 'l1_ratio': 0.3, 'early_stopping': False, 'alpha': 0.05}                                                                     | 0.186     |
| media_ocp_cv2_medium      | en       | 0.8683117027695156 | {'penalty': None, 'l1_ratio': 0.5, 'early_stopping': False, 'alpha': 0.01}                                                                     | 54.841    |
| media_ocp_kw_small        | all      | 0.8558702042868357 | {'solver': 'adam', 'learning_rate': 'constant', 'hidden_layer_sizes': (63, 38), 'early_stopping': False, 'alpha': 0.006, 'activation': 'relu'} | 1.468     |
| media_ocp_kw_tiny         | all      | 0.8136730385986041 | {'penalty': None, 'l1_ratio': 0.5, 'early_stopping': False, 'alpha': 0.005}                                                                    | 0.154     |

`*` requires `media_ocp_cv2_medium`

