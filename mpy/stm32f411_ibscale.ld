/*
    GNU linker script for STM32F411 - ibScale MP Feeder

    Reclaims the ~48K of sector 4 that the default stm32f411.ld leaves stranded:
    the filesystem is shrunk to 48K (sectors 1-3) and FLASH_TEXT is extended down to
    sector 4 (0x08010000), giving firmware 448K instead of 384K. TEXT1_ADDR in
    mpconfigboard.mk must match FLASH_TEXT's origin (0x08010000).
*/

/* Specify the memory areas */
MEMORY
{
    FLASH (rx)      : ORIGIN = 0x08000000, LENGTH = 512K /* entire flash */
    FLASH_START (rx): ORIGIN = 0x08000000, LENGTH = 16K /* sector 0 */
    FLASH_FS (rx)   : ORIGIN = 0x08004000, LENGTH = 48K /* sectors 1,2,3 (16K each) */
    FLASH_TEXT (rx) : ORIGIN = 0x08010000, LENGTH = 448K /* sector 4 (64K) + sectors 5,6,7 (128K each) */
    RAM (xrw)       : ORIGIN = 0x20000000, LENGTH = 112K
    FS_CACHE (xrw)  : ORIGIN = 0x2001c000, LENGTH = 16K
}

/* produce a link error if there is not this amount of RAM for these sections */
_minimum_stack_size = 2K;
_minimum_heap_size = 16K;

/* Define the stack.  The stack is full descending so begins just above last byte
   of RAM.  Note that EABI requires the stack to be 8-byte aligned for a call. */
_estack = ORIGIN(RAM) + LENGTH(RAM) - _estack_reserve;
_sstack = _estack - 16K; /* tunable */

/* RAM extents for the garbage collector */
_ram_start = ORIGIN(RAM);
_ram_end = ORIGIN(RAM) + LENGTH(RAM);
_heap_start = _ebss; /* heap starts just after statically allocated memory */
_heap_end = _sstack;

/* Filesystem cache in RAM, and storage in flash */
_micropy_hw_internal_flash_storage_ram_cache_start = ORIGIN(FS_CACHE);
_micropy_hw_internal_flash_storage_ram_cache_end = ORIGIN(FS_CACHE) + LENGTH(FS_CACHE);
_micropy_hw_internal_flash_storage_start = ORIGIN(FLASH_FS);
_micropy_hw_internal_flash_storage_end = ORIGIN(FLASH_FS) + LENGTH(FLASH_FS);
