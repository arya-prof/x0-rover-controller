import sys
import asyncio
import json
import cv2
import websockets
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QSlider, QFileDialog, QGridLayout, QHBoxLayout, QStyle,
    QGroupBox, QFrame
)
from PyQt5.QtCore import Qt, QSize, QTimer, QRectF
from PyQt5.QtGui import QImage, QPixmap, QIcon, QPainter, QColor, QFont, QPalette
from qasync import QEventLoop


class CircularProgress(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(120, 120)  # Larger size for better visibility
        self.battery_percentage = 0
        self.setStyleSheet("background: transparent;")

    def set_battery_percentage(self, percentage):
        """Set the battery percentage and update the display."""
        self.battery_percentage = percentage
        self.update()

    def paintEvent(self, event):
        """Custom paint event to draw the circular progress bar."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(10, 10, 100, 100)  # Circle size
        
        # Determine color based on battery level
        if self.battery_percentage > 60:
            color = QColor(0, 200, 0)  # Green
        elif self.battery_percentage > 30:
            color = QColor(255, 165, 0)  # Orange
        else:
            color = QColor(220, 0, 0)  # Red
        
        # Draw the circle background (gray)
        painter.setPen(QColor(100, 100, 100))
        painter.setBrush(QColor(50, 50, 50))
        painter.drawEllipse(rect)
        
        # Draw the circle foreground (battery status)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        start_angle = 90 * 16  # Start from the top of the circle (in 1/16th degrees)
        span_angle = int(-(self.battery_percentage * 360) * 16 / 100)  # Convert to integer
        painter.drawPie(rect, start_angle, span_angle)
        
        # Draw the percentage text in the center
        painter.setPen(QColor(255, 255, 255))  # White color for text
        painter.setFont(QFont("Arial", 16, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, f"{self.battery_percentage}%")

        painter.end()


class RoverGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("x0 Rover Controller (to the moon team)")
        self.ws = None
        self.cap = cv2.VideoCapture(0)  # Use default webcam
        self.init_ui()

        QTimer.singleShot(0, self.start_async_connection)

        # Start camera update timer
        self.camera_timer = QTimer()
        self.camera_timer.timeout.connect(self.update_camera)
        self.camera_timer.start(30)  # 30ms ~ 30 FPS

        # Default speed values
        self.speed_factor = 1  # Normal speed by default
        self.last_telemetry = {}

    def init_ui(self):
        # Main layout
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # Left panel (controls)
        left_panel = QVBoxLayout()
        left_panel.setSpacing(15)
        left_panel.setContentsMargins(10, 10, 10, 10)

        # Right panel (camera and telemetry)
        right_panel = QVBoxLayout()
        right_panel.setSpacing(15)
        right_panel.setContentsMargins(10, 10, 10, 10)

        # Add panels to main layout
        main_layout.addLayout(left_panel, 30)  # 30% width
        main_layout.addLayout(right_panel, 70)  # 70% width

        # ========== LEFT PANEL CONTROLS ========== #
        
        # Battery status group
        battery_group = QGroupBox("Rover Status")
        battery_layout = QVBoxLayout()
        
        self.battery_widget = CircularProgress()
        battery_layout.addWidget(self.battery_widget, 0, Qt.AlignCenter)
        
        # Telemetry labels
        self.battery_label = QLabel("Battery: --%")
        self.temp_label = QLabel("Temperature: --°C")
        self.imu_label = QLabel("Orientation: --")
        self.arm_label = QLabel("Arm Position: --")
        
        for label in [self.battery_label, self.temp_label, self.imu_label, self.arm_label]:
            label.setStyleSheet("font-size: 12px;")
            battery_layout.addWidget(label)
        
        battery_group.setLayout(battery_layout)
        left_panel.addWidget(battery_group)

        # Speed control group
        speed_group = QGroupBox("Speed Control")
        speed_layout = QVBoxLayout()
        
        self.speed_display_label = QLabel("Current Speed: Normal")
        self.speed_display_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        speed_layout.addWidget(self.speed_display_label)
        
        # Speed buttons
        self.normal_speed_btn = self.create_speed_button("Normal Speed", "normal")
        self.object_speed_btn = self.create_speed_button("Object Speed", "object")
        self.fast_speed_btn = self.create_speed_button("Fast Speed", "fast")
        
        speed_layout.addWidget(self.normal_speed_btn)
        speed_layout.addWidget(self.object_speed_btn)
        speed_layout.addWidget(self.fast_speed_btn)
        
        speed_group.setLayout(speed_layout)
        left_panel.addWidget(speed_group)

        # Movement controls group
        move_group = QGroupBox("Movement Controls")
        move_layout = QVBoxLayout()
        
        # Create a grid for movement buttons
        grid_layout = QGridLayout()
        grid_layout.setSpacing(5)
        
        # Movement buttons with larger size and better icons
        self.btn_fwd = self.create_movement_button("↑", "forward")
        self.btn_left = self.create_movement_button("←", "left")
        self.btn_right = self.create_movement_button("→", "right")
        self.btn_bwd = self.create_movement_button("↓", "backward")
        self.btn_stop = self.create_movement_button("◉", "stop")
        
        # Add buttons to grid
        grid_layout.addWidget(self.btn_fwd, 0, 1)
        grid_layout.addWidget(self.btn_left, 1, 0)
        grid_layout.addWidget(self.btn_stop, 1, 1)
        grid_layout.addWidget(self.btn_right, 1, 2)
        grid_layout.addWidget(self.btn_bwd, 2, 1)
        
        move_layout.addLayout(grid_layout)
        move_group.setLayout(move_layout)
        left_panel.addWidget(move_group)

        # Arm control group
        arm_group = QGroupBox("Arm Control")
        arm_layout = QVBoxLayout()
        
        self.arm_slider = QSlider(Qt.Horizontal)
        self.arm_slider.setMinimum(0)
        self.arm_slider.setMaximum(180)
        self.arm_slider.setValue(90)
        self.arm_slider.setTickInterval(10)
        self.arm_slider.setTickPosition(QSlider.TicksBelow)
        self.arm_slider.valueChanged.connect(self.arm_moved)
        
        self.lbl_arm = QLabel("Arm Angle: 90°")
        self.lbl_arm.setAlignment(Qt.AlignCenter)
        
        # Add Drop Flag button
        self.drop_flag_btn = QPushButton("Drop Flag")
        self.drop_flag_btn.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxWarning))
        self.drop_flag_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                background-color: #d9534f;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
            QPushButton:pressed {
                background-color: #ac2925;
            }
        """)
        self.drop_flag_btn.clicked.connect(self.drop_flag)
        
        arm_layout.addWidget(self.lbl_arm)
        arm_layout.addWidget(self.arm_slider)
        arm_layout.addWidget(self.drop_flag_btn)
        arm_group.setLayout(arm_layout)
        left_panel.addWidget(arm_group)

        # Media buttons
        media_group = QGroupBox("Media")
        media_layout = QHBoxLayout()
        
        self.screenshot_btn = QPushButton("Screenshot")
        self.screenshot_btn.setIcon(self.style().standardIcon(QStyle.SP_DesktopIcon))
        self.screenshot_btn.clicked.connect(self.take_screenshot)
        
        self.take_photo_btn = QPushButton("Take Photo")
        self.take_photo_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        self.take_photo_btn.clicked.connect(self.take_photo)
        
        media_layout.addWidget(self.screenshot_btn)
        media_layout.addWidget(self.take_photo_btn)
        media_group.setLayout(media_layout)
        left_panel.addWidget(media_group)

        # Add stretch to push everything up
        left_panel.addStretch()

        # ========== RIGHT PANEL CAMERA/TELEMETRY ========== #
        
        # Camera preview
        camera_group = QGroupBox("Camera Feed")
        camera_layout = QVBoxLayout()
        
        self.camera_label = QLabel("Camera loading...")
        self.camera_label.setMinimumSize(640, 480)
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setStyleSheet("""
            border: 2px solid #444;
            border-radius: 5px;
            background: #222;
            color: #fff;
            padding: 10px;
        """)
        
        camera_layout.addWidget(self.camera_label)
        camera_group.setLayout(camera_layout)
        right_panel.addWidget(camera_group)

        # Detailed telemetry
        telemetry_group = QGroupBox("Detailed Telemetry")
        telemetry_layout = QVBoxLayout()
        
        self.telemetry_label = QLabel("Waiting for telemetry data...")
        self.telemetry_label.setWordWrap(True)
        self.telemetry_label.setStyleSheet("font-family: monospace;")
        
        telemetry_layout.addWidget(self.telemetry_label)
        telemetry_group.setLayout(telemetry_layout)
        right_panel.addWidget(telemetry_group)

        # Apply styles
        self.apply_styles()

    def create_movement_button(self, text, direction):
        btn = QPushButton(text)
        btn.setFixedSize(60, 60)
        btn.setStyleSheet("""
            QPushButton {
                font-size: 24px;
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 30px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #444, stop:1 #333);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #666, stop:1 #555);
            }
        """)
        btn.clicked.connect(lambda: self.send_cmd("move", {"dir": direction}))
        return btn

    def create_speed_button(self, text, speed_type):
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                border: 1px solid #444;
                border-radius: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #555, stop:1 #444);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                          stop:0 #777, stop:1 #666);
            }
        """)
        
        if speed_type == "normal":
            btn.clicked.connect(self.set_normal_speed)
        elif speed_type == "object":
            btn.clicked.connect(self.set_object_speed)
        elif speed_type == "fast":
            btn.clicked.connect(self.set_fast_speed)
        
        return btn

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                background: #333;
                color: #eee;
            }
            QGroupBox {
                border: 1px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: #444;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                          stop:0 #eee, stop:1 #ccc);
                border: 1px solid #555;
                border-radius: 8px;
                margin: -4px 0;
            }
            QSlider::sub-page:horizontal {
                background: #5a8;
                border-radius: 4px;
            }
        """)

    def update_camera(self):
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            bytes_per_line = 3 * width
            qimg = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg).scaled(
                self.camera_label.width(), 
                self.camera_label.height(), 
                Qt.KeepAspectRatio
            )
            self.camera_label.setPixmap(pixmap)
        else:
            self.camera_label.setText("Camera not available")

    def start_async_connection(self):
        asyncio.create_task(self.connect_websocket())

    async def connect_websocket(self):
        try:
            self.ws = await websockets.connect("ws://localhost:8765")
            self.telemetry_label.setText("Connected to Rover!")
            asyncio.create_task(self.receive_data())
        except Exception as e:
            self.telemetry_label.setText(f"Error connecting: {e}")

    def send_cmd(self, cmd_type, data):
        if self.ws:
            # Apply speed factor to movement commands
            if cmd_type == "move" and "speed" not in data:
                data["speed"] = self.speed_factor
                
            msg = {"cmd": cmd_type}
            msg.update(data)
            asyncio.create_task(self.ws.send(json.dumps(msg)))

    async def receive_data(self):
        try:
            while True:
                message = await self.ws.recv()
                telemetry = json.loads(message)
                self.last_telemetry = telemetry
                
                # Update battery
                battery = telemetry.get("battery", "--")
                self.battery_widget.set_battery_percentage(battery)
                self.battery_label.setText(f"Battery: {battery}%")
                
                # Update temperature
                temp = telemetry.get("temp", "--")
                self.temp_label.setText(f"Temperature: {temp}°C")
                
                # Update IMU data
                imu = telemetry.get("imu", {})
                pitch = imu.get("pitch", "--")
                roll = imu.get("roll", "--")
                self.imu_label.setText(f"Orientation: Pitch {pitch}°, Roll {roll}°")
                
                # Update arm position
                arm = telemetry.get("arm", "--")
                self.arm_label.setText(f"Arm Position: {arm}°")
                
                # Update detailed telemetry
                display = json.dumps(telemetry, indent=2)
                self.telemetry_label.setText(f"Telemetry:\n{display}")
                
        except Exception as e:
            self.telemetry_label.setText(f"Disconnected: {e}")

    def arm_moved(self, value):
        self.lbl_arm.setText(f"Arm Angle: {value}°")
        self.send_cmd("arm", {"joint": 1, "angle": value})

    def drop_flag(self):
        """Handle the drop flag command."""
        self.send_cmd("flag", {"action": "drop"})
        self.telemetry_label.setText("Flag dropped!")

    def set_normal_speed(self):
        self.speed_factor = 1
        self.speed_display_label.setText("Current Speed: Normal")
        self.update_speed_buttons("normal")

    def set_object_speed(self):
        self.speed_factor = 0.5
        self.speed_display_label.setText("Current Speed: Object")
        self.update_speed_buttons("object")

    def set_fast_speed(self):
        self.speed_factor = 2
        self.speed_display_label.setText("Current Speed: Fast")
        self.update_speed_buttons("fast")

    def update_speed_buttons(self, active):
        """Update button styles based on which speed is active"""
        buttons = {
            "normal": self.normal_speed_btn,
            "object": self.object_speed_btn,
            "fast": self.fast_speed_btn
        }
        
        for name, btn in buttons.items():
            if name == active:
                btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        border: 2px solid #5a8;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #5a8, stop:1 #496);
                        font-weight: bold;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        padding: 8px;
                        border: 1px solid #444;
                        border-radius: 4px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                stop:0 #555, stop:1 #444);
                    }
                """)

    def take_screenshot(self):
        """Capture and save a screenshot of the interface."""
        filename, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Screenshot", 
            "", 
            "JPEG Files (*.jpg);;PNG Files (*.png)"
        )
        if filename:
            screenshot = self.grab()
            screenshot.save(filename)

    def take_photo(self):
        """Capture a photo using the camera and save it."""
        ret, frame = self.cap.read()
        if ret:
            filename, _ = QFileDialog.getSaveFileName(
                self, 
                "Save Photo", 
                "", 
                "JPEG Files (*.jpg);;PNG Files (*.png)"
            )
            if filename:
                cv2.imwrite(filename, frame)  # Save frame to file
        else:
            self.telemetry_label.setText("Error capturing photo.")

    def closeEvent(self, event):
        self.cap.release()
        if self.ws:
            asyncio.get_event_loop().run_until_complete(self.ws.close())
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Set dark palette
    app.setStyle('Fusion')
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(35, 35, 35))
    dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(dark_palette)

    window = RoverGUI()
    window.showMaximized()

    with loop:
        loop.run_forever()