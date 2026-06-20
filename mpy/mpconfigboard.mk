MCU_SERIES = f4
CMSIS_MCU = STM32F411xE
AF_FILE = boards/stm32f411_af.csv
# Custom linker script: 48K filesystem (sectors 1-3) + 448K firmware (sectors 4-7),
# reclaiming the ~48K the stock stm32f411.ld strands in sector 4. TEXT1_ADDR must
# match FLASH_TEXT's origin (0x08010000).
LD_FILES = $(BOARD_DIR)/stm32f411_ibscale.ld boards/common_ifs.ld
TEXT0_ADDR = 0x08000000
TEXT1_ADDR = 0x08010000

MICROPY_VFS_LFS2 = 1

FROZEN_MANIFEST ?= $(BOARD_DIR)/manifest.py

# SPI-flash variant scaffolding (the default build uses internal flash). The 25 MHz HSE
# crystal is fixed in hardware, so the clock is hardcoded in mpconfigboard.h (PLLM=25) and
# stm32f4xx_hal_conf.h (HSE_VALUE), not parameterized via XTAL_FREQ_MHZ.

ifdef SPI_FLASH_SIZE_MB
BUILD := $(BUILD)_FLASH_$(SPI_FLASH_SIZE_MB)M
endif

# No flash chip in default build - use internal flash
SPI_FLASH_SIZE_MB ?= 0

CFLAGS += -DMICROPY_HW_SPIFLASH_SIZE_BYTES="($(SPI_FLASH_SIZE_MB) * 1024 * 1024)"

# GCC 16 newly flags an unused 'debug' variable in the vendored ST HAL (ll_usb.c) as
# -Werror=unused-but-set-variable. Keep it a warning so the build completes without
# patching submodule code. Appended via CFLAGS_EXTRA so it lands after -Werror.
CFLAGS_EXTRA += -Wno-error=unused-but-set-variable
