// Lesson 1.10, step "Show it on the LED grid": a happy face when the soil is fine, a sad face when it is dry.
// Change REFILL_POINT to your tray's refill point (Our tray on the website).
#include <AgriSenseStudent.h>
#include "Arduino_LED_Matrix.h"

const float REFILL_POINT = 18.0;          // % moisture
AgriSenseStudent trainer;
ArduinoLEDMatrix grid;

uint8_t happy[8][12] = {
  {0,0,0,0,0,0,0,0,0,0,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,1,0,0,0,0,0,0,1,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,0,0,1,1,1,1,0,0,0,0}, {0,0,0,0,0,0,0,0,0,0,0,0}};
uint8_t sad[8][12] = {
  {0,0,0,0,0,0,0,0,0,0,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,0,0,0,0,0,0,0,0,0,0},
  {0,0,0,0,1,1,1,1,0,0,0,0}, {0,0,0,1,0,0,0,0,1,0,0,0}, {0,0,1,0,0,0,0,0,0,1,0,0}, {0,0,0,0,0,0,0,0,0,0,0,0}};

void setup() {
  Serial.begin(115200);
  grid.begin();
  trainer.begin();
}

void loop() {
  if (trainer.update() && trainer.probeOk()) {
    float m = trainer.moisture();
    Serial.print("Moisture "); Serial.println(m, 1);
    if (m < REFILL_POINT) grid.renderBitmap(sad, 8, 12);     // too dry
    else grid.renderBitmap(happy, 8, 12);
  }
  delay(1000);
}
