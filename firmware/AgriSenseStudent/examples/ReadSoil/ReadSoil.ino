// Lesson 1.10, step "Read the soil": print the Trainer's soil reading every 2 seconds.
// Open the Serial Monitor at 115200 and compare with "Our tray" on the website.
#include <AgriSenseStudent.h>

AgriSenseStudent trainer;

void setup() {
  Serial.begin(115200);
  delay(1500);
  trainer.begin();
  Serial.println("AgriSense: reading the soil...");
}

void loop() {
  if (trainer.update()) {
    Serial.print("Moisture ");   Serial.print(trainer.moisture(), 1); Serial.print(" %   ");
    Serial.print("Soil temp ");  Serial.print(trainer.soilTemp(), 1); Serial.print(" C   ");
    Serial.print("EC ");         Serial.print(trainer.ec(), 0);      Serial.print("   ");
    Serial.print("pH ");         Serial.println(trainer.ph(), 1);
    if (!trainer.probeOk()) Serial.println("  (no probe reading: is the probe in the PROBE socket?)");
  } else {
    Serial.println("No answer from the Trainer. Check the Qwiic cable in the STUDENT socket.");
  }
  delay(2000);
}
