# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                             |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------- | -------: | -------: | ------: | --------: |
| ovos\_core/\_\_init\_\_.py                       |        7 |        0 |    100% |           |
| ovos\_core/\_\_main\_\_.py                       |       26 |       26 |      0% |     21-89 |
| ovos\_core/intent\_services/\_\_init\_\_.py      |        1 |        0 |    100% |           |
| ovos\_core/intent\_services/converse\_service.py |      189 |       47 |     75% |39-40, 44-47, 84, 133-136, 143-150, 152-153, 155-156, 167-170, 187-190, 209, 212, 306-310, 324-325, 340-344, 348-352, 364, 376, 384 |
| ovos\_core/intent\_services/fallback\_service.py |       94 |       11 |     88% |52-54, 78, 81, 91, 109-111, 125, 159-160 |
| ovos\_core/intent\_services/service.py           |      322 |       95 |     70% |53, 127-128, 165-167, 214-215, 236, 250-251, 253-254, 256-257, 304-305, 349, 367-383, 467, 473-475, 477-479, 483-484, 525-537, 546-549, 554-555, 563-586, 596-598, 602-604, 616-635, 639 |
| ovos\_core/intent\_services/stop\_service.py     |      152 |       12 |     92% |153-154, 159-161, 170, 198, 262, 298, 309, 344, 375, 388 |
| ovos\_core/skill\_installer.py                   |      204 |       87 |     57% |56-65, 72, 89-124, 143-190, 248, 266, 275-292, 296 |
| ovos\_core/skill\_manager.py                     |      341 |      100 |     71% |52, 105, 125-126, 210, 287, 289, 293-297, 303, 305, 358-360, 368-376, 380-411, 417-420, 424-428, 444-446, 456-478, 492-493, 496-497, 502, 506, 520-521, 533-535, 548-549, 561-563, 578-579, 583-584, 586-589, 591-594, 598-599 |
| ovos\_core/transformers.py                       |      132 |       37 |     72% |31, 35-37, 68-69, 89-98, 114-117, 134-140, 179, 184-186, 200-204, 222-223 |
| ovos\_core/version.py                            |       17 |        3 |     82% | 23, 34-35 |
|                                        **TOTAL** | **1485** |  **418** | **72%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/OpenVoiceOS/ovos-core/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OpenVoiceOS/ovos-core/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FOpenVoiceOS%2Fovos-core%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.