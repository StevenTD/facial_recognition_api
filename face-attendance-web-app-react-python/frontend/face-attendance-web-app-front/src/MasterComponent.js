import React, { useEffect, useState } from "react";
import axios from "axios";
import API_BASE_URL from "./API";
import toast, { Toaster } from "react-hot-toast";
import { FiLogOut, FiUserPlus, FiSettings, FiDownload, FiArrowLeft, FiCheck, FiX } from "react-icons/fi";
import Webcam from "react-webcam";
import { useFaceDetection } from "react-use-face-detection";
import { FaceDetection } from "@mediapipe/face_detection";
import { Camera } from "@mediapipe/camera_utils";

function dataURItoBlob(dataURI) {
  var byteString = atob(dataURI.split(',')[1]);
  var mimeString = dataURI.split(',')[0].split(':')[1].split(';')[0];
  var ab = new ArrayBuffer(byteString.length);
  var ia = new Uint8Array(ab);
  for (var i = 0; i < byteString.length; i++) {
    ia[i] = byteString.charCodeAt(i);
  }
  return new Blob([ab], { type: mimeString });
}

function MasterComponent() {
  const [showImg, setShowImg] = useState(false);

  const { webcamRef, boundingBox, isLoading, detected, facesDetected } = useFaceDetection({
    faceDetectionOptions: {
      model: 'short',
    },
    faceDetection: new FaceDetection({
      locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_detection@0.4.1646425229/${file}`,
    }),
    camera: ({ mediaSrc, onFrame, width, height }) =>
      new Camera(mediaSrc, {
        onFrame,
        width,
        height,
      }),
  });

  const [isRegistering, setIsRegistering] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [value, setValue] = useState("");
  const [lastFrame, setLastFrame] = useState(null);

  // States for automated log flow
  const [countdown, setCountdown] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [loginData, setLoginData] = useState(null);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Clock effect
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  // Timer for auto-login with buffer
  useEffect(() => {
    let timerId;

    if (isRegistering || isAdmin || loginData !== null) {
      setCountdown(null);
      return;
    }

    if (detected && facesDetected > 0 && !isProcessing) {
      if (countdown === null) {
        setCountdown(3);
      } else if (countdown > 0) {
        timerId = setTimeout(() => {
          setCountdown(countdown - 1);
        }, 1000);
      } else if (countdown === 0) {
        // Trigger login sequence
        setIsProcessing(true);
        setCountdown(null);
        send_img_login();

        // Wait 5 seconds before attempting another login detection loop
        setTimeout(() => {
          setIsProcessing(false);
          setLoginData(null); // Clear the Identity Card after 5s
        }, 5000);
      }
    } else {
      if (!isProcessing && countdown !== null) {
        setCountdown(null);
      }
    }

    return () => {
      if (timerId) clearTimeout(timerId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detected, facesDetected, countdown, isRegistering, isAdmin, isProcessing, loginData]);

  function register_new_user_ok(text) {
    if (lastFrame) {
      const apiUrl = API_BASE_URL + "/register_new_user?text=" + text;
      const blob = dataURItoBlob(lastFrame);
      const file = new File([blob], "webcam-frame.png", { type: "image/png" });
      const formData = new FormData();
      formData.append("file", file);

      axios
        .post(apiUrl, formData, {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        })
        .then((response) => {
          if (response.data.registration_status === 200) {
            toast.success("User was registered successfully!");
          }
        })
        .catch((error) => {
          console.error("Error sending image to API:", error);
          if (error.response && error.response.data && error.response.data.error) {
            toast.error(error.response.data.error);
          } else {
            toast.error("Registration failed!");
          }
        });
    }
  }

  async function downloadLogs() {
    try {
      const response = await axios.get(API_BASE_URL + "/get_attendance_logs", {
        responseType: "blob",
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "logs.zip");
      document.body.appendChild(link);
      link.click();
      toast.success("Logs downloaded successfully");
    } catch (error) {
      toast.error("Failed to download logs");
    }
  }

  function send_img_login() {
    if (webcamRef.current) {
      const imageSrc = webcamRef.current.getScreenshot();
      if (!imageSrc) return;

      const blob = dataURItoBlob(imageSrc);
      const apiUrl = API_BASE_URL + "/login";
      const file = new File([blob], "webcam-frame.png", { type: "image/png" });
      const formData = new FormData();
      formData.append("file", file);

      axios
        .post(apiUrl, formData, {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        })
        .then((response) => {
          if (response.data.match_status === true) {
            // Display Persistent Identity Card instead of toast
            setLoginData({
              username: response.data.user,
              imageSrc: imageSrc,
              timestamp: new Date()
            });
          } else {
            console.log("Unknown user detected and ignored.");
          }
        })
        .catch((error) => {
          console.error("Error sending image to API:", error);
        });
    }
  }

  function send_img_logout() {
    if (webcamRef.current) {
      const imageSrc = webcamRef.current.getScreenshot();
      if (!imageSrc) return;

      const blob = dataURItoBlob(imageSrc);
      const apiUrl = API_BASE_URL + "/logout";
      const file = new File([blob], "webcam-frame.png", { type: "image/png" });
      const formData = new FormData();
      formData.append("file", file);

      axios
        .post(apiUrl, formData, {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        })
        .then((response) => {
          if (response.data.match_status === true) {
            toast.success("Goodbye " + response.data.user + " !");
          } else {
            toast.error("Unknown user! Please try again or register new user!");
          }
        })
        .catch((error) => {
          console.error("Error sending image to API:", error);
          toast.error("Logout request failed.");
        });
    }
  }

  const renderButtons = () => {
    if (isRegistering) {
      return (
        <div className="buttons-container register-flow">
          <input
            className="input-field"
            type="text"
            placeholder="Enter user name"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <button
            className="btn-success"
            onClick={async () => {
              setIsAdmin(false);
              setIsRegistering(false);
              setShowImg(false);
              if (value.trim() === "") {
                toast.error("Please enter a username");
              } else {
                register_new_user_ok(value);
              }
            }}
          >
            <FiCheck size={20} /> Register User
          </button>
          <button
            className="btn-danger"
            onClick={async () => {
              setIsAdmin(false);
              setIsRegistering(false);
              setShowImg(false);
            }}
          >
            <FiX size={20} /> Cancel
          </button>
        </div>
      );
    }

    if (isAdmin) {
      return (
        <div className="buttons-container">
          <button
            className="btn-primary"
            onClick={() => {
              setIsAdmin(false);
              setIsRegistering(true);
              if (webcamRef.current) {
                setLastFrame(webcamRef.current.getScreenshot());
                setShowImg(true);
              }
              setValue("");
            }}
          >
            <FiUserPlus size={20} /> Register New User
          </button>
          <button
            className="btn-success"
            onClick={() => {
              setIsAdmin(false);
              setIsRegistering(false);
              downloadLogs();
            }}
          >
            <FiDownload size={20} /> Download Logs
          </button>
          <button
            className="btn-secondary"
            onClick={() => {
              setIsAdmin(false);
              setIsRegistering(false);
            }}
          >
            <FiArrowLeft size={20} /> Go Back
          </button>
        </div>
      );
    }

    // Default state: login is automated, so just show Logout & Admin Tools
    return (
      <div className="buttons-container">
        <button
          className="btn-success"
          onClick={() => {
            send_img_logout();
          }}
        >
          <FiLogOut size={20} /> Logout
        </button>
        <button
          className="btn-secondary"
          onClick={() => {
            setIsAdmin(true);
            setIsRegistering(false);
          }}
        >
          <FiSettings size={20} /> Admin Tools
        </button>
      </div>
    );
  };

  return (
    <div className="master-component">
      <Toaster position="top-right" toastOptions={{
        className: 'custom-toast',
        style: { background: '#333', color: '#fff', borderRadius: '10px' }
      }} />
      <div className="webcam-container" style={{ position: 'relative' }}>

        {/* Standby Clock */}
        {!loginData && (
          <div className="clock-overlay">
            <p className="clock-time">
              {currentTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </p>
            <p className="clock-date">
              {currentTime.toLocaleDateString([], { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
            </p>
          </div>
        )}

        {/* Countdown Overlays */}
        {countdown !== null && countdown > 0 && !loginData && (
          <div className="countdown-overlay">
            <p className="pulse-text">Stay still...</p>
            <h1 className="countdown-number">{countdown}</h1>
          </div>
        )}

        {/* Success Identity Card */}
        {loginData && (
          <div className="identity-card">
            <div className="id-header">
              <img src={loginData.imageSrc} alt="Profile" className="id-avatar" />
              <div className="id-title">
                <h2 className="id-name">{loginData.username}</h2>
                <p className="id-role">Identity Verified</p>
              </div>
            </div>

            <div className="id-details">
              <div className="id-row">
                <span className="id-label">Fullname</span>
                <span className="id-value">Pending Assignment</span>
              </div>
              <div className="id-row">
                <span className="id-label">Office</span>
                <span className="id-value">Pending Assignment</span>
              </div>
              <div className="id-row">
                <span className="id-label">Department</span>
                <span className="id-value">Pending Assignment</span>
              </div>

              <div className="id-row id-time-row">
                <span className="id-label">Time Recorded</span>
                <span className="id-value">
                  {loginData.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
              </div>
            </div>
          </div>
        )}

        {!showImg ? (
          <>
            <div style={{ position: 'relative', display: 'inline-block', width: '100%', maxWidth: '600px' }}>
              <Webcam
                ref={webcamRef}
                audio={false}
                videoConstraints={{
                  facingMode: "user"
                }}
                screenshotFormat="image/png"
                className="img"
                style={{ display: "block", width: "100%", height: "auto", borderRadius: '8px' }}
              />
              {boundingBox.map((box, index) => (
                <div
                  key={index}
                  style={{
                    border: '3px solid #10b981',
                    position: 'absolute',
                    top: `${box.yCenter * 115}%`,
                    left: `${box.xCenter * 125}%`,
                    width: `${box.width * 145}%`,
                    height: `${box.height * 145}%`,
                    transform: 'translate(-50%, -50%)',
                    zIndex: 2,
                    pointerEvents: 'none',
                    borderRadius: '4px'
                  }}
                />
              ))}
            </div>
          </>
        ) : (
          <img className="img" src={lastFrame} alt="Captured frame" />
        )}
        {isLoading && <div style={{ position: 'absolute', top: 10, left: 10, background: 'rgba(0,0,0,0.5)', padding: '5px', borderRadius: '5px', pointerEvents: 'none', zIndex: 3, color: 'white' }}>Loading Face Model...</div>}
      </div>
      {renderButtons()}
    </div>
  );
}

export default MasterComponent;
