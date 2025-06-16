# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                             |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------- | -------: | -------: | ------: | --------: |
| ovos\_core/\_\_init\_\_.py                       |        7 |        0 |    100% |           |
| ovos\_core/\_\_main\_\_.py                       |       31 |       31 |      0% |     21-77 |
| ovos\_core/intent\_services/\_\_init\_\_.py      |        1 |        0 |    100% |           |
| ovos\_core/intent\_services/converse\_service.py |      184 |       96 |     48% |34-35, 39-42, 64-79, 93-108, 127-166, 181-186, 204, 207, 301-305, 319-320, 335-339, 343-347, 354-359, 366-371, 379, 383-387 |
| ovos\_core/intent\_services/fallback\_service.py |       94 |       13 |     86% |52-54, 78, 81, 91, 109-111, 125, 159-160, 190-191 |
| ovos\_core/intent\_services/service.py           |      322 |      117 |     64% |53, 57, 127-128, 165-167, 214-215, 236, 250-251, 253-254, 256-257, 270-272, 304-305, 349, 367-383, 404-410, 443-444, 467, 483-484, 525-537, 546-549, 554-555, 563-586, 590-612, 616-635, 639 |
| ovos\_core/intent\_services/stop\_service.py     |      149 |       17 |     89% |153-154, 159-161, 170, 198, 262, 298, 305, 309, 313-316, 344, 375, 388 |
| ovos\_core/skill\_installer.py                   |      186 |       74 |     60% |53-62, 69, 86-121, 140-187, 245, 263 |
| ovos\_core/skill\_manager.py                     |      301 |       82 |     73% |48, 96, 190, 267, 269, 273-277, 283, 285, 338-340, 348-356, 360-391, 397-400, 404-408, 424-426, 436-458, 472-473, 478, 482, 496-497, 509-511, 524-525, 537-539 |
| ovos\_core/transformers.py                       |      132 |       43 |     67% |31, 35-37, 53-57, 68-69, 89-98, 113-117, 134-140, 179, 184-186, 200-204, 222-223 |
| ovos\_core/version.py                            |       17 |       17 |      0% |      2-35 |
|                                        **TOTAL** | **1424** |  **490** | **66%** |           |


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