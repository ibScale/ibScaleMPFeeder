// based off the following reference board:
// * https://github.com/micropython/micropython/tree/master/ports/stm32/boards/WEACT_F411_BLACKPILL

#define MICROPY_HW_BOARD_NAME       "ibScaleMPFeeder"
#define MICROPY_HW_MCU_NAME         "STM32F411CE"
#define MICROPY_HW_FLASH_FS_LABEL   "MPFEEDER"
#define MICROPY_PY_SYS_PLATFORM     "GluonPNP"

// some users having issues with FLASH_LATENCY_2, so set to 3
// from https://forum.micropython.org/viewtopic.php?t=7154
#define MICROPY_HW_FLASH_LATENCY    FLASH_LATENCY_3

// Enabled hardware options
#define MICROPY_HW_HAS_FLASH        (1)
#define MICROPY_HW_ENABLE_RTC       (0)
#define MICROPY_HW_ENABLE_USB       (1)
#define MICROPY_HW_ENABLE_RNG       (0)
#define MICROPY_HW_ENABLE_TIMER     (1)
#define MICROPY_HW_USB_FS           (1)
#define MICROPY_HW_USB_MSC          (1) // Compiled in; suppressed at boot by boot.py (VCP only).
                                        // Enabled at runtime when dropping to the REPL (VCP+MSC).
#define MICROPY_HW_HAS_SWITCH       (0) // GPIO works better with more flexibility
#define MICROPY_HW_HAS_ADC          (1)

// Configure PLL for final CPU freq of 96MHz
#define MICROPY_HW_CLK_PLLM (25)
#define MICROPY_HW_CLK_PLLN (192)
#define MICROPY_HW_CLK_PLLP (RCC_PLLP_DIV2)
#define MICROPY_HW_CLK_PLLQ (4)

// NOTE: the buttons, drive-enable output, ADC voltage monitors, quadrature encoder,
// motor/peel PWM and 1-Wire EEPROM are all configured by the frozen Python drivers
// (lib/hardware/*) using the pin names in pins.csv - not by board #defines. Only the
// hardware that MicroPython's C side owns (LEDs via pyb.LED, UART2 for RS485) is below.

// RGB LEDs, by default PWM hardware assumes common Anode, where High is ON and Low is OFF
// For common Cathode LEDs you need to invert the output in software. For example, with
// common Anode you would call LED.on() to turn the LED ON. With common Cathode you would
// call LED.off() to turn the LED ON instead. Therefore LED.intensity(254) is almost full
// brightness on common Anode while being the dimmest setting on common Cathode.
// This took longer then it should have to figure out and I'm still pissed about it. Feel my rage
#define MICROPY_HW_LED1           (pyb_pin_LEDRED)
#define MICROPY_HW_LED2           (pyb_pin_LEDGREEN)
#define MICROPY_HW_LED3           (pyb_pin_LEDBLUE)
#define MICROPY_HW_LED1_PWM       { TIM1, 1, TIM_CHANNEL_1, GPIO_AF1_TIM1 }
#define MICROPY_HW_LED2_PWM       { TIM1, 2, TIM_CHANNEL_2, GPIO_AF1_TIM1 }
#define MICROPY_HW_LED3_PWM       { TIM1, 3, TIM_CHANNEL_3, GPIO_AF1_TIM1 }
#define MICROPY_HW_LED_ON(pin)    (mp_hal_pin_high(pin))
#define MICROPY_HW_LED_OFF(pin)   (mp_hal_pin_low(pin))

// RS485
#define MICROPY_HW_UART2_NAME   "RS485"
#define MICROPY_HW_UART2_TX     (pyb_pin_RS485TX)
#define MICROPY_HW_UART2_RX     (pyb_pin_RS485RX)
#define MICROPY_HW_UART2_RTS    (pyb_pin_RS485DE)

// Use USB for REPL
//#define MICROPY_HW_UART_REPL        (NULL)

// External SPI Flash configuration
#if !defined(MICROPY_HW_SPIFLASH_SIZE_BYTES) || (MICROPY_HW_SPIFLASH_SIZE_BYTES == 0)
// Use internal filesystem if spiflash not enabled.
#define MICROPY_HW_ENABLE_INTERNAL_FLASH_STORAGE (1)

#else
// Reserve SPI flash bus.
#define MICROPY_HW_SPI_IS_RESERVED(id)  (id == 1)

// Disable internal filesystem to use spiflash.
#define MICROPY_HW_ENABLE_INTERNAL_FLASH_STORAGE (0)

// SPI flash pins
#define MICROPY_HW_SPIFLASH_CS          (pyb_pin_FLASHNSS)
#define MICROPY_HW_SPIFLASH_SCK         (pyb_pin_FLASHSCK)
#define MICROPY_HW_SPIFLASH_MOSI        (pyb_pin_FLASHMOSI)
#define MICROPY_HW_SPIFLASH_MISO        (pyb_pin_FLASHMISO)

extern const struct _mp_spiflash_config_t spiflash_config;
extern struct _spi_bdev_t spi_bdev;
#define MICROPY_HW_SPIFLASH_ENABLE_CACHE (1)
#define MICROPY_HW_BDEV_SPIFLASH    (&spi_bdev)
#define MICROPY_HW_BDEV_SPIFLASH_CONFIG (&spiflash_config)
#define MICROPY_HW_BDEV_SPIFLASH_SIZE_BYTES (MICROPY_HW_SPIFLASH_SIZE_BYTES)
#define MICROPY_HW_BDEV_SPIFLASH_EXTENDED (&spi_bdev) // for extended block protocol
#define MICROPY_HW_SPIFLASH_SIZE_BITS (MICROPY_HW_SPIFLASH_SIZE_BYTES * 8)
#endif
