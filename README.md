# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/OpenVoiceOS/ovos-core/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                              |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------------- | -------: | -------: | ------: | --------: |
| ovos\_core/\_\_init\_\_.py                        |        7 |        0 |    100% |           |
| ovos\_core/\_\_main\_\_.py                        |       31 |       31 |      0% |     21-77 |
| ovos\_core/intent\_services/\_\_init\_\_.py       |      465 |      171 |     63% |48-49, 52-53, 125, 128, 134-135, 141, 159-160, 182, 194-195, 215-221, 249-256, 276, 282, 304-306, 319-320, 322-323, 325-326, 339-341, 373-374, 382-386, 429, 447-463, 484-490, 523-524, 547, 553-555, 557-559, 563-564, 604-616, 625-628, 633-634, 668, 679, 683-702, 708-716, 721-728, 732-739, 743-750, 754-761, 765-772, 776-783, 787-794, 798-805, 809-816, 820-827, 831-838, 842-849, 853-860, 864-871, 875-882, 886-893, 897, 905, 913, 921, 929, 937, 945, 953, 961, 969 |
| ovos\_core/intent\_services/adapt\_service.py     |        5 |        5 |      0% |       2-8 |
| ovos\_core/intent\_services/commonqa\_service.py  |        5 |        5 |      0% |       1-7 |
| ovos\_core/intent\_services/converse\_service.py  |      207 |      139 |     33% |34-35, 39-42, 64-79, 93-108, 127-166, 181-186, 200-208, 226-256, 280-313, 349-355, 365-369, 373-377, 384-389, 396-401, 405-406, 414, 418-424 |
| ovos\_core/intent\_services/fallback\_service.py  |      109 |       57 |     48% |45-55, 58-60, 74-81, 98-107, 110-122, 138-165, 194-199, 221-222 |
| ovos\_core/intent\_services/ocp\_service.py       |        5 |        5 |      0% |       2-8 |
| ovos\_core/intent\_services/padacioso\_service.py |        6 |        6 |      0% |       2-9 |
| ovos\_core/intent\_services/padatious\_service.py |        5 |        5 |      0% |       2-8 |
| ovos\_core/intent\_services/stop\_service.py      |      146 |       76 |     48% |49-50, 72-130, 156-180, 208, 222-225, 232-237, 268, 280, 292, 314-343, 378, 391 |
| ovos\_core/skill\_installer.py                    |      186 |       74 |     60% |53-62, 69, 86-121, 140-187, 245, 263 |
| ovos\_core/skill\_manager.py                      |      426 |      140 |     67% |54-56, 72, 121, 217, 294, 296, 311, 313, 366-368, 376-404, 410-413, 417-421, 425-433, 437-445, 449-457, 461-463, 474, 476, 478, 487-516, 519-529, 541-544, 565-577, 590-591, 606-609, 614-620, 651-652, 657, 661, 676-677, 689-691, 704-705, 717-719, 742, 757-762, 766, 781-786 |
| ovos\_core/transformers.py                        |      132 |       43 |     67% |31, 35-37, 53-57, 68-69, 89-98, 113-117, 134-140, 179, 184-186, 200-204, 222-223 |
| ovos\_core/version.py                             |       17 |       17 |      0% |      2-35 |
|                                         **TOTAL** | **1752** |  **774** | **56%** |           |


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