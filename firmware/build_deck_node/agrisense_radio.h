// AgriSense Lab - LoRa radio setup shared by the gateway, the pump node and the sensor nodes.
// The same file is in each sketch folder (Arduino needs it next to the .ino): keep the copies identical.
//
// Board is picked from Tools > Board:
//   XIAO_ESP32S3 (2026 kits): Seeed XIAO ESP32S3 + Wio-SX1262 kit, FCC IDs Z4T-XIAOESP32S3 and Z4TWIOSX1262.
//     The Wio-SX1262 sits on the XIAO's B2B connector: NSS GPIO41, DIO1 GPIO39, RST GPIO42, BUSY GPIO40,
//     RF switch on DIO2 + RXEN GPIO38, TCXO 1.8 V, SPI on D8-D10 (GPIO7/8/9): never wire anything to D8-D10.
//   Heltec WiFi LoRa 32 V3 (first kits): NSS 8, DIO1 14, RST 12, BUSY 13.
//
// Radio settings (FCC, Nov 2026): the Wio-SX1262 was tested and certified on 903.0-914.2 MHz with 500 kHz
// LoRa channels (FCC test report BL-SZ2480665-602). We use one of those channels, 909.4 MHz at 500 kHz, and
// 14 dBm (the report measured up to 19.6 dBm). Do not change these to "make range better": a different
// channel width or frequency is outside what was certified. Every node and the gateway must match.
#pragma once
#include <RadioLib.h>
#include <SPI.h>

const float LORA_MHZ = 909.4;
const float LORA_BW_KHZ = 500.0;
const uint8_t LORA_SF = 9, LORA_CR = 7, LORA_SYNC = 0x12;
const int8_t LORA_DBM = 14;

#if defined(ARDUINO_XIAO_ESP32S3)
SX1262 radio = new Module(41, 39, 42, 40);
#else
SX1262 radio = new Module(8, 14, 12, 13);
#endif

// Returns RADIOLIB_ERR_NONE (0) when the radio is ready.
inline int radioBegin() {
#if defined(ARDUINO_XIAO_ESP32S3)
  SPI.begin(7, 8, 9, 41);
  int st = radio.begin(LORA_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC, LORA_DBM, 8, 1.8);
  if (st == RADIOLIB_ERR_NONE) {
    radio.setDio2AsRfSwitch(true);
    radio.setRfSwitchPins(38, RADIOLIB_NC);
  }
  return st;
#else
  return radio.begin(LORA_MHZ, LORA_BW_KHZ, LORA_SF, LORA_CR, LORA_SYNC, LORA_DBM);
#endif
}
