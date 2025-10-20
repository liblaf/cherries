# Changelog

## [0.6.0](https://github.com/liblaf/cherries/compare/v0.5.5..v0.6.0) - 2025-10-20

### 💥 BREAKING CHANGES

- Migrate decorator implementation to `wrapt` - ([eb62820](https://github.com/liblaf/cherries/commit/eb6282055c78ffbcde17cba3fa7f750d1b1a822d))

### 🐛 Bug Fixes

- **comet:** Refactor experiment handling and logging - ([2907d47](https://github.com/liblaf/cherries/commit/2907d47dcb86d84ca4f83c57b101206c81adbecf))

### ❤️ New Contributors

- [@liblaf](https://github.com/liblaf) made their first contribution
- [@liblaf-bot[bot]](https://github.com/apps/liblaf-bot) made their first contribution

## [0.5.5](https://github.com/liblaf/cherries/compare/v0.5.4..v0.5.5) - 2025-10-14

### 🐛 Bug Fixes

- **plugins/comet:** make DVC asset logging conditional - ([2bdeb1e](https://github.com/liblaf/cherries/commit/2bdeb1ecb2874d909a29f8967e729a6082306ab8))

## [0.5.4](https://github.com/liblaf/cherries/compare/v0.5.3..v0.5.4) - 2025-10-13

### ✨ Features

- **plugins:** log Git-tracked files as remote assets in Comet - ([8f92b65](https://github.com/liblaf/cherries/commit/8f92b65cfe8d0771675f3cd633082e218835297b))

### 🐛 Bug Fixes

- **plugins/comet:** use raw GitHub URL for git-tracked assets - ([71809f1](https://github.com/liblaf/cherries/commit/71809f1fad89b1df713b48df5c571c900ccd34e2))

### ♻ Code Refactoring

- **core:** Overhaul experiment naming and artifact organization - ([5421366](https://github.com/liblaf/cherries/commit/54213669171d33b9d4dadbcf87f79b831495b166))

## [0.5.3](https://github.com/liblaf/cherries/compare/v0.5.2..v0.5.3) - 2025-10-07

### ✨ Features

- **profiles:** add Dvc plugin to playground profile - ([2befcdd](https://github.com/liblaf/cherries/commit/2befcddac06f20430ef2c378fa9e0c8c6e0c1efb))

## [0.5.2](https://github.com/liblaf/cherries/compare/v0.5.1..v0.5.2) - 2025-09-29

### 👷 Build System

- **deps:** Add cachetools and refine dvc dependencies - ([6989a98](https://github.com/liblaf/cherries/commit/6989a98994ed612476cde55c43c62984eaa5f4ff))

## [0.5.1](https://github.com/liblaf/cherries/compare/v0.5.0..v0.5.1) - 2025-09-29

### ♻ Code Refactoring

- overhaul plugin system and introduce advanced asset management - ([63e2931](https://github.com/liblaf/cherries/commit/63e2931bdc2f30f96824d5a8277e3355015b09e9))

## [0.5.0](https://github.com/liblaf/cherries/compare/v0.4.3..v0.5.0) - 2025-09-28

### 💥 BREAKING CHANGES

- reorganize path utilities and enhance plugin integrations - ([76faff3](https://github.com/liblaf/cherries/commit/76faff39252277c38035882dc06949e9d5f003e1))

### 🐛 Bug Fixes

- **plugins/comet:** correctly handle DVC asset paths in Comet integration - ([16358b0](https://github.com/liblaf/cherries/commit/16358b0e0a46ebd0411b49ff123761be6ab215cc))

### ♻ Code Refactoring

- centralize type definitions in typing module - ([6555f95](https://github.com/liblaf/cherries/commit/6555f95f81fdd9a6064fd647c170b5d1b769df81))

## [0.4.3](https://github.com/liblaf/cherries/compare/v0.4.2..v0.4.3) - 2025-09-16

### ✨ Features

- **git:** add option to skip git hooks during auto-commit - ([7ab310e](https://github.com/liblaf/cherries/commit/7ab310e17b9697180de29b34abd847b16c21c66b))

## [0.4.2](https://github.com/liblaf/cherries/compare/v0.4.1..v0.4.2) - 2025-09-15

### 🐛 Bug Fixes

- update scripts to pass arguments correctly and improve CI workflow - ([fb7de6f](https://github.com/liblaf/cherries/commit/fb7de6f72e3a61bb8e2b5f2508be4a5213891958))

### 📝 Documentation

- update project documentation and metadata - ([7d5454c](https://github.com/liblaf/cherries/commit/7d5454c4495002c025c1b7f284a9f86b54f27d14))

### ♻ Code Refactoring

- **plugins/logging:** simplify logging initialization and update grapes dependency - ([ec1f5ee](https://github.com/liblaf/cherries/commit/ec1f5ee0e1117ad68c8b3d14b52ca3ad54fbfe56))

## [0.4.1](https://github.com/liblaf/cherries/compare/v0.4.0..v0.4.1) - 2025-09-04

### 🐛 Bug Fixes

- trigger release - ([c885239](https://github.com/liblaf/cherries/commit/c8852398ad82bd1147b228a35e465743c4d3f10c))

## [0.4.0](https://github.com/liblaf/cherries/compare/v0.3.1..v0.4.0) - 2025-08-25

### 💥 BREAKING CHANGES

- trigger release - ([8c55deb](https://github.com/liblaf/cherries/commit/8c55deb6b5472c35d6e02c61b7ebbb077e95380a))

## [0.3.1](https://github.com/liblaf/cherries/compare/v0.3.0..v0.3.1) - 2025-08-19

### ✨ Features

- **plugins, profiles:** Add Git plugin for auto-commit and enhance profile configuration - ([2ddea7a](https://github.com/liblaf/cherries/commit/2ddea7afc3329ddc44e0d421e489cfaeffb5f2f9))

## [0.3.0](https://github.com/liblaf/cherries/compare/v0.2.2..v0.3.0) - 2025-07-28

### 💥 BREAKING CHANGES

- **core:** add DVC integration and refactor logging - ([3737462](https://github.com/liblaf/cherries/commit/37374627fa3a1eb7327dc8d32f2a0a63ae8bf5bf))

### ✨ Features

- **config:** add model_dump_without_assets function - ([b30a407](https://github.com/liblaf/cherries/commit/b30a4072ad5bdc96da440124d1b5d22cce4a011c))
- **plugins:** add Local plugin for file operations - ([08349a1](https://github.com/liblaf/cherries/commit/08349a19ebaa64f7058ffddf5a829fd505c1d931))

## [0.2.2](https://github.com/liblaf/cherries/compare/v0.2.1..v0.2.2) - 2025-07-22

### ✨ Features

- **core:** expand logging and monitoring capabilities - ([8c14c94](https://github.com/liblaf/cherries/commit/8c14c940d4fb2ffb04963b445dab0dc57c690dd1))
- **plugins:** add Comet integration - ([fa8b046](https://github.com/liblaf/cherries/commit/fa8b046bb887b3f334d1106865651a539a1fbdd6))

### 🐛 Bug Fixes

- **plugins:** ensure proper execution order and compatibility - ([3f2d50a](https://github.com/liblaf/cherries/commit/3f2d50a9e3348d197bb5ebf28ec2885d9cf6ee0b))

### ♻ Code Refactoring

- **core:** replace custom decorators with wrapt - ([9c88ce3](https://github.com/liblaf/cherries/commit/9c88ce3bf956ec38e22ce274c6a159fc0d5c211d))

## [0.2.1](https://github.com/liblaf/cherries/compare/v0.2.0..v0.2.1) - 2025-07-19

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to v1 (#43) - ([1f20bd0](https://github.com/liblaf/cherries/commit/1f20bd020cba3403542288d6d3a23879208258ac))

## [0.2.0](https://github.com/liblaf/cherries/compare/v0.1.7..v0.2.0) - 2025-07-15

### 💥 BREAKING CHANGES

- **core:** redesign plugin system architecture - ([b437d45](https://github.com/liblaf/cherries/commit/b437d4526207008e73b9f3cb564635d5a008c6d9))

## [0.1.7](https://github.com/liblaf/cherries/compare/v0.1.6..v0.1.7) - 2025-07-14

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to >=0.4,<0.5 (#39) - ([c34ce44](https://github.com/liblaf/cherries/commit/c34ce44cad668403f3f7780872aad7ff963b07c1))

## [0.1.6](https://github.com/liblaf/cherries/compare/v0.1.5..v0.1.6) - 2025-06-23

### ⬆️ Dependencies

- **deps:** relax dependency version constraints - ([29ea5f3](https://github.com/liblaf/cherries/commit/29ea5f30ec2ff5ee6f7bdadb5b13f016ab0dc1fc))

## [0.1.5](https://github.com/liblaf/cherries/compare/v0.1.4..v0.1.5) - 2025-06-23

### ⬆️ Dependencies

- **deps:** update documentation and core dependencies - ([4b23e62](https://github.com/liblaf/cherries/commit/4b23e623779f3c50b6e89909bee735f52f1edf34))

## [0.1.4](https://github.com/liblaf/cherries/compare/v0.1.3..v0.1.4) - 2025-06-09

### ✨ Features

- **core:** add plugin system and experiment base - ([d1cd38b](https://github.com/liblaf/cherries/commit/d1cd38b799464668529df5de52480d82c6639c65))

## [0.1.3](https://github.com/liblaf/cherries/compare/v0.1.2..v0.1.3) - 2025-06-08

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to >=0.2,<0.3 (#34) - ([57266ba](https://github.com/liblaf/cherries/commit/57266baaecdedce9f15b23fe77dbe5641f8e8cea))

## [0.1.2](https://github.com/liblaf/cherries/compare/v0.1.1..v0.1.2) - 2025-05-25

### ✨ Features

- **integration:** add current_exp and logging functions for inputs/outputs - ([1713f7a](https://github.com/liblaf/cherries/commit/1713f7abec989fc9dc5e5288b29ebb1e017f33a1))

## [0.1.1](https://github.com/liblaf/cherries/compare/v0.1.0..v0.1.1) - 2025-05-25

### 🐛 Bug Fixes

- improve DVC initialization and remote setup - ([321d203](https://github.com/liblaf/cherries/commit/321d203017bd2a1fc185574c566a20bd92c76ca5))

## [0.1.0](https://github.com/liblaf/cherries/compare/v0.0.14..v0.1.0) - 2025-05-24

### 💥 BREAKING CHANGES

- **cherries:** refactor experiment tracking and add Comet.ml integration - ([aa4d02d](https://github.com/liblaf/cherries/commit/aa4d02da2c7d6ea64129e3f8b2c0a32902fc0d5e))

### 📝 Documentation

- update copier configuration files - ([025bf1f](https://github.com/liblaf/cherries/commit/025bf1f47dc133b2245887617bb160230eac5ac7))

## [0.0.14](https://github.com/liblaf/cherries/compare/v0.0.13..v0.0.14) - 2025-05-22

### 🐛 Bug Fixes

- migrate from just to mise for task management - ([54ca742](https://github.com/liblaf/cherries/commit/54ca742dd74fb908f27842526d53c46350ef71e9))

## [0.0.13](https://github.com/liblaf/cherries/compare/v0.0.12..v0.0.13) - 2025-05-09

### 🐛 Bug Fixes

- use enum for run status and rename exp-dir tag - ([358ccfd](https://github.com/liblaf/cherries/commit/358ccfda5b5827e614109241a999a6d3b78b6bce))

### ♻ Code Refactoring

- **cherries:** rename exp_dir to run_dir and enhance DVC/MLflow integration - ([cd04a2f](https://github.com/liblaf/cherries/commit/cd04a2f1f617c8e05b2d655fc9ee76499b686e83))

## [0.0.12](https://github.com/liblaf/cherries/compare/v0.0.11..v0.0.12) - 2025-05-07

### ✨ Features

- **cherries:** add run status tracking and progress monitoring - ([c6d31a2](https://github.com/liblaf/cherries/commit/c6d31a22606397953678a570f8bd25c9e5b266c7))

## [0.0.11](https://github.com/liblaf/cherries/compare/v0.0.10..v0.0.11) - 2025-05-06

### ✨ Features

- **plugin:** add log_src function to track source files - ([513a025](https://github.com/liblaf/cherries/commit/513a0252ac4dcf6aa54863e214436e3df1f3d541))

## [0.0.10](https://github.com/liblaf/cherries/compare/v0.0.9..v0.0.10) - 2025-05-06

### ✨ Features

- **cherries:** enhance experiment tracking and path handling - ([3bc705e](https://github.com/liblaf/cherries/commit/3bc705ebf7eb6eea42d488f4f6e353ed09bc9db4))
- **cherries:** migrate from neptune to mlflow and dvc - ([f5143c1](https://github.com/liblaf/cherries/commit/f5143c13b1d6d4b5cb0d227a9dc5f2a0505a508d))

## [0.0.9](https://github.com/liblaf/cherries/compare/v0.0.8..v0.0.9) - 2025-03-31

### ✨ Features

- enhance project configuration and testing setup - ([70c0f7b](https://github.com/liblaf/cherries/commit/70c0f7bce25df2569037e7466936d2a18bcaa222))

### 🐛 Bug Fixes

- update dependencies and improve type hint handling - ([39bd70d](https://github.com/liblaf/cherries/commit/39bd70d03574f708640a21160ef31ab9f9af5f63))

### ⬆️ Dependencies

- **deps:** update dependency rich to v14 (#21) - ([1b6793c](https://github.com/liblaf/cherries/commit/1b6793cac5ee6462c6772ec33293a81c8968009b))

### 🔧 Continuous Integration

- update docs workflows and dependencies - ([64e3619](https://github.com/liblaf/cherries/commit/64e36192ec71967f911beba70ad31047f1958178))

## [0.0.8](https://github.com/liblaf/cherries/compare/v0.0.7..v0.0.8) - 2025-03-19

### ⬆️ Dependencies

- **deps:** update liblaf-grapes to v0.1.10 - ([4cc961b](https://github.com/liblaf/cherries/commit/4cc961b2b1bff865cc6c5edb1f3a4e36f60c6bf6))

## [0.0.7](https://github.com/liblaf/cherries/compare/v0.0.6..v0.0.7) - 2025-03-19

### 🔧 Continuous Integration

- update release-please config and manifest file paths - ([2bdd359](https://github.com/liblaf/cherries/commit/2bdd359c8644742c67e03e69af21e92c739f1d32))

## [0.0.6](https://github.com/liblaf/cherries/compare/v0.0.5..v0.0.6) - 2025-03-16

### 👷 Build System

- enhance build and linting process - ([e0ef806](https://github.com/liblaf/cherries/commit/e0ef8063063fddd43aa53b3ef7257b865e7f2fce))

## [0.0.5](https://github.com/liblaf/cherries/compare/v0.0.4..v0.0.5) - 2025-03-11

### ♻ Code Refactoring

- streamline git repository handling and logging configuration - ([08d2dc3](https://github.com/liblaf/cherries/commit/08d2dc3879af78da7441b02f831e55d3fb982a4b))

## [0.0.4](https://github.com/liblaf/cherries/compare/v0.0.3..v0.0.4) - 2025-02-24

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to >=0.1.2,<0.1.3 (#14) - ([43d2db5](https://github.com/liblaf/cherries/commit/43d2db5e0fa0c9684c233e0bd10d201e60617afa))
- **deps:** update dependency liblaf-grapes to >=0.1.1,<0.1.2 (#12) - ([7167242](https://github.com/liblaf/cherries/commit/716724275eb08b04cb52d78f8145d86bdaef4ba9))

## [0.0.3](https://github.com/liblaf/cherries/compare/v0.0.2..v0.0.3) - 2025-02-17

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to >=0.1.0,<0.1.1 (#11) - ([3578378](https://github.com/liblaf/cherries/commit/3578378ca5b0fe861bd72dfbe462fabbd1a4e978))
- **deps:** update dependency liblaf-grapes to >=0.0.5,<0.0.6 (#10) - ([ae48be8](https://github.com/liblaf/cherries/commit/ae48be80c7a17575dad2f1e2e876ad7abcd5480e))
- **deps:** update dependency liblaf-grapes to >=0.0.4,<0.0.5 (#8) - ([4dc1845](https://github.com/liblaf/cherries/commit/4dc18458b69222408d9889abd4609a957deddfdd))

## [0.0.2](https://github.com/liblaf/cherries/compare/v0.0.1..v0.0.2) - 2025-02-04

### ⬆️ Dependencies

- **deps:** update dependency liblaf-grapes to >=0.0.3,<0.0.4 (#7) - ([654faa9](https://github.com/liblaf/cherries/commit/654faa9033f3a911b39f7e5c64439cbab7c80591))
- **deps:** update dependency liblaf-grapes to >=0.0.1,<0.0.2 (#4) - ([2c3f56e](https://github.com/liblaf/cherries/commit/2c3f56eac1858effe88d0a09671df3ab39dc367c))

### ❤️ New Contributors

- [@github-actions[bot]](https://github.com/apps/github-actions) made their first contribution in [#6](https://github.com/liblaf/cherries/pull/6)
- [@renovate[bot]](https://github.com/apps/renovate) made their first contribution in [#7](https://github.com/liblaf/cherries/pull/7)

## [0.0.1](https://github.com/liblaf/cherries/compare/v0.0.0..v0.0.1) - 2025-01-19

### ✨ Features

- **cherries:** enhance experiment tracking and logging capabilities - ([093e56e](https://github.com/liblaf/cherries/commit/093e56ec73b1d1c86a46bfe9893a09f0f51f4f39))
- **cherries:** refactor experiment tracking and add new features - ([8594ac1](https://github.com/liblaf/cherries/commit/8594ac1ff3f782d4aba7072c9f92ad3091ea64b7))
- **integration:** enhance logging support for unsupported types - ([019b5b7](https://github.com/liblaf/cherries/commit/019b5b7130f9a2612c3f58c4e89c3e4b954f724a))
- **logging:** enhance file logging with custom filter for cherries module - ([d03a6a1](https://github.com/liblaf/cherries/commit/d03a6a1b3bab3eeca929520dee33e6542a46766e))
- log experiment entrypoint for better traceability - ([06c3f84](https://github.com/liblaf/cherries/commit/06c3f84bf4e675229ae73be2ad5978b2d9a282c1))

### ♻ Code Refactoring

- sort plugins by priority and reverse iteration order - ([33d98e4](https://github.com/liblaf/cherries/commit/33d98e4f613adad1f756950e6cf26e0b0bf6787d))
- remove unused integration base class and update gitignore - ([4015f84](https://github.com/liblaf/cherries/commit/4015f846b0d7436280cc018cf60f46a46d5e3ec5))

### ❤️ New Contributors

- [@liblaf-bot[bot]](https://github.com/apps/liblaf-bot) made their first contribution

## [0.0.0] - 2025-01-16

### ✨ Features

- add logging and restic plugins, extend run capabilities - ([f28d30f](https://github.com/liblaf/cherries/commit/f28d30f990a9cbc876c16e98f8fdf5a2e7f54746))

### ♻ Code Refactoring

- simplify Run class by removing abstract base class - ([d267065](https://github.com/liblaf/cherries/commit/d26706537fc81d4abd4be87d29511259774053ad))

### 👷 Build System

- restructure project and enhance git integration - ([bbc24c0](https://github.com/liblaf/cherries/commit/bbc24c019640371f110aaae98d3bf178c8f353f0))
- initialize project structure and configuration - ([91d27cf](https://github.com/liblaf/cherries/commit/91d27cf861b724b1cbaf923eceac7e0177edcadb))

### ❤️ New Contributors

- [@release-please[bot]](https://github.com/apps/release-please) made their first contribution in [#1](https://github.com/liblaf/cherries/pull/1)
- [@liblaf](https://github.com/liblaf) made their first contribution
