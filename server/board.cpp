#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>

// WiFi credentials
const char* ssid = "YourWiFiSSID";
const char* password = "YourWiFiPassword";

// WebSocket server
WebSocketsServer webSocket = WebSocketsServer(8765);

// Motor control pins (adjust according to your setup)
const int motorA1 = 12;  // Right motor forward
const int motorA2 = 13;  // Right motor backward
const int motorB1 = 14;  // Left motor forward
const int motorB2 = 15;  // Left motor backward

// Servo control
Servo armServo;
Servo cameraServo;
const int armPin = 2;     // GPIO for arm servo
const int cameraPin = 4;  // GPIO for camera servo
int armAngle = 90;        // Initial arm position (0-180)
int cameraAngle = 90;     // Initial camera position (0-180)

// Speed control
float currentSpeed = 1.0;  // Normal speed (0.0 to 1.0)

// Battery simulation (replace with actual battery monitoring)
unsigned long lastBatteryUpdate = 0;
int batteryLevel = 100;

// IMU simulation (replace with actual IMU code)
float pitch = 0.0;
float roll = 0.0;

void setup() {
  Serial.begin(115200);
  
  // Initialize motor control pins
  pinMode(motorA1, OUTPUT);
  pinMode(motorA2, OUTPUT);
  pinMode(motorB1, OUTPUT);
  pinMode(motorB2, OUTPUT);
  
  // Initialize servos
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  armServo.setPeriodHertz(50);  // Standard 50hz servo
  cameraServo.setPeriodHertz(50);
  armServo.attach(armPin, 500, 2400);
  cameraServo.attach(cameraPin, 500, 2400);
  armServo.write(armAngle);
  cameraServo.write(cameraAngle);
  
  // Connect to WiFi
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());
  
  // Start WebSocket server
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
}

void loop() {
  webSocket.loop();
  
  // Simulate battery drain (replace with actual battery monitoring)
  if (millis() - lastBatteryUpdate > 10000) { // Every 10 seconds
    lastBatteryUpdate = millis();
    batteryLevel = max(0, batteryLevel - 1); // Decrease by 1% every 10 seconds
    
    // Send telemetry update
    sendTelemetry();
  }
  
  // Simulate IMU data (replace with actual IMU code)
  pitch = sin(millis() / 5000.0) * 15.0; // -15 to +15 degrees
  roll = cos(millis() / 7000.0) * 10.0;  // -10 to +10 degrees
}

void webSocketEvent(uint8_t num, WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.printf("[%u] Disconnected!\n", num);
      stopMotors();
      break;
      
    case WStype_CONNECTED:
      {
        IPAddress ip = webSocket.remoteIP(num);
        Serial.printf("[%u] Connected from %d.%d.%d.%d\n", num, ip[0], ip[1], ip[2], ip[3]);
        // Send initial telemetry when a client connects
        sendTelemetry();
      }
      break;
      
    case WStype_TEXT:
      handleCommand((char*)payload);
      break;
      
    case WStype_ERROR:
    case WStype_FRAGMENT_TEXT_START:
    case WStype_FRAGMENT_BIN_START:
    case WStype_FRAGMENT:
    case WStype_FRAGMENT_FIN:
      break;
  }
}

void handleCommand(char* payload) {
  StaticJsonDocument<256> doc;
  DeserializationError error = deserializeJson(doc, payload);
  
  if (error) {
    Serial.print("deserializeJson() failed: ");
    Serial.println(error.c_str());
    return;
  }
  
  const char* cmd = doc["cmd"];
  
  if (strcmp(cmd, "move") == 0) {
    const char* dir = doc["dir"];
    float speed = doc["speed"] | currentSpeed; // Use current speed if not specified
    
    if (strcmp(dir, "forward") == 0) {
      moveForward(speed);
    } else if (strcmp(dir, "backward") == 0) {
      moveBackward(speed);
    } else if (strcmp(dir, "left") == 0) {
      turnLeft(speed);
    } else if (strcmp(dir, "right") == 0) {
      turnRight(speed);
    } else if (strcmp(dir, "forward_left") == 0) {
      moveForwardLeft(speed);
    } else if (strcmp(dir, "forward_right") == 0) {
      moveForwardRight(speed);
    } else if (strcmp(dir, "backward_left") == 0) {
      moveBackwardLeft(speed);
    } else if (strcmp(dir, "backward_right") == 0) {
      moveBackwardRight(speed);
    } else if (strcmp(dir, "stop") == 0) {
      stopMotors();
    }
  } 
  else if (strcmp(cmd, "arm") == 0) {
    int joint = doc["joint"];
    int angle = doc["angle"];
    
    if (joint == 1) { // Main arm joint
      armAngle = constrain(angle, 0, 180);
      armServo.write(armAngle);
      sendTelemetry();
    }
  } 
  else if (strcmp(cmd, "camera") == 0) {
    int angle = doc["angle"];
    cameraAngle = constrain(angle, 0, 180);
    cameraServo.write(cameraAngle);
    sendTelemetry();
  } 
  else if (strcmp(cmd, "flag") == 0) {
    const char* action = doc["action"];
    if (strcmp(action, "drop") == 0) {
      dropFlag();
    }
  }
}

void sendTelemetry() {
  StaticJsonDocument<256> doc;
  doc["battery"] = batteryLevel;
  
  JsonObject imu = doc.createNestedObject("imu");
  imu["pitch"] = pitch;
  imu["roll"] = roll;
  
  doc["arm"] = armAngle;
  
  String output;
  serializeJson(doc, output);
  webSocket.broadcastTXT(output);
}

// Movement functions
void moveForward(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, pwm);
  analogWrite(motorA2, 0);
  analogWrite(motorB1, pwm);
  analogWrite(motorB2, 0);
}

void moveBackward(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, 0);
  analogWrite(motorA2, pwm);
  analogWrite(motorB1, 0);
  analogWrite(motorB2, pwm);
}

void turnLeft(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, pwm);
  analogWrite(motorA2, 0);
  analogWrite(motorB1, 0);
  analogWrite(motorB2, pwm);
}

void turnRight(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, 0);
  analogWrite(motorA2, pwm);
  analogWrite(motorB1, pwm);
  analogWrite(motorB2, 0);
}

void moveForwardLeft(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, pwm);
  analogWrite(motorA2, 0);
  analogWrite(motorB1, pwm/2);
  analogWrite(motorB2, 0);
}

void moveForwardRight(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, pwm/2);
  analogWrite(motorA2, 0);
  analogWrite(motorB1, pwm);
  analogWrite(motorB2, 0);
}

void moveBackwardLeft(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, 0);
  analogWrite(motorA2, pwm);
  analogWrite(motorB1, 0);
  analogWrite(motorB2, pwm/2);
}

void moveBackwardRight(float speed) {
  int pwm = (int)(255 * speed);
  analogWrite(motorA1, 0);
  analogWrite(motorA2, pwm/2);
  analogWrite(motorB1, 0);
  analogWrite(motorB2, pwm);
}

void stopMotors() {
  analogWrite(motorA1, 0);
  analogWrite(motorA2, 0);
  analogWrite(motorB1, 0);
  analogWrite(motorB2, 0);
}

void dropFlag() {
  // Implement flag dropping mechanism here
  // For example, you might use a servo to release a flag
  // This is a placeholder - adjust for your hardware
  Servo flagServo;
  flagServo.attach(5); // Use an appropriate pin
  flagServo.write(180); // Release flag
  delay(500);
  flagServo.detach();
  
  // Send telemetry update
  sendTelemetry();
}