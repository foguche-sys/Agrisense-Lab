// Lesson 1.10, steps "Ask for water" and "Test the safety".
// When the soil is below THRESHOLD, ask the Trainer for a RUN_SECONDS pump run. The Trainer answers
// OK or REFUSED with a reason. Try RUN_SECONDS = 120, then ask twice in a minute: what happens?
#include <AgriSenseStudent.h>

const float THRESHOLD = 18.0;    // % moisture: your tray's refill point
const int RUN_SECONDS = 10;      // how long to ask for (the Trainer allows 1 to 20)
AgriSenseStudent trainer;

void setup() {
  Serial.begin(115200);
  delay(1500);
  trainer.begin();
  Serial.println("AgriSense: watching the soil. Ask your teacher to unlock the controls.");
}

void loop() {
  if (!trainer.update()) { Serial.println("No answer from the Trainer. Check the STUDENT cable."); delay(3000); return; }
  float m = trainer.moisture();
  Serial.print("Moisture "); Serial.print(m, 1); Serial.println(" %");
  if (m < THRESHOLD && !trainer.pumpOn()) {
    Serial.print("Dry! Asking for "); Serial.print(RUN_SECONDS); Serial.println(" s of water...");
    uint8_t answer = trainer.askForWater(RUN_SECONDS);
    Serial.println(AgriSenseStudent::reason(answer));
    if (answer == AS_TOO_SOON) { Serial.print("Wait "); Serial.print(trainer.waitSeconds()); Serial.println(" s"); }
    delay(15000);                // give the water time to soak in before checking again
  }
  delay(3000);
}
