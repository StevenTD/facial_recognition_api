import React, { useEffect, useState } from "react";
import axios from "axios";
import API_BASE_URL from "./API";
import toast, { Toaster } from "react-hot-toast";
import { FiLogOut, FiUserPlus, FiSettings, FiDownload, FiArrowLeft, FiCheck, FiX, FiVideo, FiVideoOff } from "react-icons/fi";
import Webcam from "react-webcam";
import { FaceMesh } from "@mediapipe/face_mesh";
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

function FaceDetectionScanner({
  isRegistering,
  isAdmin,
  loginData,
  isProcessing,
  setIsProcessing,
  setLoginData,
  setScreenshotRef,
  livenessMode
}) {
  const webcamRef = React.useRef(null);
  const [isLoading, setIsLoading] = useState(true);
  const [facesDetected, setFacesDetected] = useState(0);
  const [faceMeshResults, setFaceMeshResults] = useState(null);
  const [countdown, setCountdown] = useState(null);
  const [blinkDetected, setBlinkDetected] = useState(false);
  const [awaitingBlink, setAwaitingBlink] = useState(false);

  // EAR Thresholds & Refs to avoid closure staleness
  const EAR_THRESHOLD = 0.22;
  const EAR_CONSEC_FRAMES = 1; // Lowered to 1 for faster detection
  const earCounterRef = React.useRef(0);
  const blinkDetectedRef = React.useRef(false);

  // Initialize Face Mesh
  useEffect(() => {
    const faceMesh = new FaceMesh({
      locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`,
    });

    faceMesh.setOptions({
      maxNumFaces: 1,
      refineLandmarks: true,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });

    faceMesh.onResults((results) => {
      setFaceMeshResults(results);
      setFacesDetected(results.multiFaceLandmarks?.length || 0);
      setIsLoading(false);

      if (results.multiFaceLandmarks && results.multiFaceLandmarks.length > 0) {
        const landmarks = results.multiFaceLandmarks[0];
        
        // Calculate EAR for Blink Detection
        // Left Eye: 33 (corner), 160(top), 158(top), 133(corner), 153(bottom), 144(bottom)
        const getDist = (p1, p2) => Math.sqrt(Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2));
        
        const leftEAR = (getDist(landmarks[160], landmarks[144]) + getDist(landmarks[158], landmarks[153])) / (2 * getDist(landmarks[33], landmarks[133]));
        const rightEAR = (getDist(landmarks[385], landmarks[380]) + getDist(landmarks[387], landmarks[373])) / (2 * getDist(landmarks[362], landmarks[263]));
        
        const avgEAR = (leftEAR + rightEAR) / 2;

        if (avgEAR < EAR_THRESHOLD) {
          earCounterRef.current += 1;
        } else {
          if (earCounterRef.current >= EAR_CONSEC_FRAMES && !blinkDetectedRef.current) {
            console.log("Blink Detected! EAR:", avgEAR.toFixed(3));
            blinkDetectedRef.current = true;
            setBlinkDetected(true);
          }
          earCounterRef.current = 0;
        }
      }
    });

    if (webcamRef.current && webcamRef.current.video) {
      const camera = new Camera(webcamRef.current.video, {
        onFrame: async () => {
          if (webcamRef.current && webcamRef.current.video) {
            await faceMesh.send({ image: webcamRef.current.video });
          }
        },
        width: 640,
        height: 480,
      });
      camera.start();
    }

    return () => faceMesh.close();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync webcam ref to parent for one-off captures
  useEffect(() => {
    setScreenshotRef(webcamRef);
    return () => setScreenshotRef(null);
  }, [webcamRef, setScreenshotRef]);

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
            setLoginData({
              username: response.data.user,
              imageSrc: imageSrc,
              timestamp: new Date()
            });
          }
        })
        .catch((error) => {
          console.error("Error sending image to API:", error);
          if (error.response && error.response.data && error.response.data.error) {
            toast.error(error.response.data.error);
          }
        });
    }
  }

  // Handle Scan Logic based on Mode
  useEffect(() => {
    let timerId;
    if (isRegistering || isAdmin || loginData !== null || isProcessing) {
      setCountdown(null);
      setAwaitingBlink(false);
      return;
    }

    if (facesDetected > 0) {
      if (livenessMode === 'blink') {
        if (!blinkDetected && !awaitingBlink) {
          setAwaitingBlink(true);
          blinkDetectedRef.current = false; // Reset ref
        } else if (blinkDetected) {
          setIsProcessing(true);
          setBlinkDetected(false);
          blinkDetectedRef.current = false;
          setAwaitingBlink(false);
          send_img_login();
          setTimeout(() => {
            setIsProcessing(false);
            setLoginData(null);
          }, 5000);
        }
      } else {
        // Standard Timer Mode
        if (countdown === null) {
          setCountdown(3);
        } else if (countdown > 0) {
          timerId = setTimeout(() => {
            setCountdown(countdown - 1);
          }, 1000);
        } else if (countdown === 0) {
          setIsProcessing(true);
          setCountdown(null);
          send_img_login();
          setTimeout(() => {
            setIsProcessing(false);
            setLoginData(null);
          }, 5000);
        }
      }
    } else {
      setCountdown(null);
      setAwaitingBlink(false);
      setBlinkDetected(false);
    }
    return () => {
      if (timerId) clearTimeout(timerId);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facesDetected, countdown, isRegistering, isAdmin, isProcessing, loginData, livenessMode, blinkDetected, awaitingBlink]);

  // Calculate box from landmarks if available
  const getBox = () => {
    if (!faceMeshResults?.multiFaceLandmarks?.[0]) return null;
    const lms = faceMeshResults.multiFaceLandmarks[0];
    
    // Mirror the X coordinates because the webcam component is mirrored={true}
    const x = lms.map(p => 1 - p.x);
    const y = lms.map(p => p.y);
    
    const minX = Math.min(...x);
    const maxX = Math.max(...x);
    const minY = Math.min(...y);
    const maxY = Math.max(...y);
    return {
      x: minX * 100,
      y: minY * 100,
      width: (maxX - minX) * 100,
      height: (maxY - minY) * 100
    };
  };

  const box = getBox();
  const borderColor = awaitingBlink ? '#f59e0b' : (blinkDetected || (countdown === 0)) ? '#10b981' : '#3b82f6';

  return (
    <div style={{ position: 'relative', display: 'inline-block', width: '100%', maxWidth: '600px' }}>
      <Webcam
        ref={webcamRef}
        audio={false}
        mirrored={true}
        videoConstraints={{
          facingMode: "user"
        }}
        screenshotFormat="image/png"
        className="img"
        style={{ display: "block", width: "100%", height: "auto", borderRadius: '8px' }}
      />
      
      {box && (
        <div
          style={{
            border: `3px solid ${borderColor}`,
            position: 'absolute',
            top: `${box.y}%`,
            left: `${box.x}%`,
            width: `${box.width}%`,
            height: `${box.height}%`,
            zIndex: 2,
            pointerEvents: 'none',
            borderRadius: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.3s ease'
          }}
        >
          {countdown !== null && countdown > 0 && (
            <div className="face-countdown">{countdown}</div>
          )}
          {awaitingBlink && !blinkDetected && (
            <div className="blink-prompt" style={{ color: '#f59e0b', fontSize: '24px', fontWeight: 'bold', textAlign: 'center', textShadow: '0 2px 4px rgba(0,0,0,0.5)' }}>
              Blink now
            </div>
          )}
        </div>
      )}

      {isLoading && (
        <div style={{ position: 'absolute', top: 10, left: 10, background: 'rgba(0,0,0,0.5)', padding: '5px', borderRadius: '5px', pointerEvents: 'none', zIndex: 3, color: 'white' }}>
          Initializing High-Security Engine...
        </div>
      )}
      
      {((countdown !== null && countdown > 0) || awaitingBlink) && !loginData && (
        <div className="countdown-overlay">
          <p className="pulse-text" style={{ color: awaitingBlink ? '#f59e0b' : 'white' }}>
            {awaitingBlink ? "Verifying Liveness..." : "Stay still..."}
          </p>
        </div>
      )}
    </div>
  );
}

function MasterComponent() {
  const [showImg, setShowImg] = useState(false);
  const [isRegistering, setIsRegistering] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [value, setValue] = useState("");
  const [lastFrame, setLastFrame] = useState(null);
  const [isCameraPaused, setIsCameraPaused] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [loginData, setLoginData] = useState(null);
  const [currentTime, setCurrentTime] = useState(new Date());
  const [livenessMode, setLivenessMode] = useState(localStorage.getItem('livenessMode') || 'standard');
  
  // Shared ref for one-off screenshot captures
  const [scannerRef, setScannerRef] = useState(null);

  useEffect(() => {
    localStorage.setItem('livenessMode', livenessMode);
  }, [livenessMode]);

  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

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

  function send_img_logout() {
    if (scannerRef && scannerRef.current) {
      const imageSrc = scannerRef.current.getScreenshot();
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
          if (error.response && error.response.data && error.response.data.error) {
            toast.error(error.response.data.error);
          } else {
            toast.error("Logout request failed.");
          }
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
          <div className="settings-card" style={{ background: 'rgba(255,255,255,0.05)', padding: '20px', borderRadius: '12px', marginBottom: '10px' }}>
            <h3 style={{ margin: '0 0 15px 0', fontSize: '16px', color: '#94a3b8' }}>Security Mode</h3>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button 
                className={livenessMode === 'standard' ? "btn-primary" : "btn-secondary"} 
                style={{ fontSize: '14px', padding: '10px' }}
                onClick={() => setLivenessMode('standard')}
              >
                Standard
              </button>
              <button 
                className={livenessMode === 'blink' ? "btn-primary" : "btn-secondary"} 
                style={{ fontSize: '14px', padding: '10px' }}
                onClick={() => setLivenessMode('blink')}
              >
                High Security
              </button>
            </div>
            <p style={{ fontSize: '12px', color: '#64748b', marginTop: '10px' }}>
              {livenessMode === 'blink' ? "Requires physical blink detection." : "Uses 3-second stay-still timer."}
            </p>
          </div>
          <button
            className="btn-primary"
            onClick={() => {
              setIsAdmin(false);
              setIsRegistering(true);
              if (scannerRef && scannerRef.current) {
                setLastFrame(scannerRef.current.getScreenshot());
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
          className={isCameraPaused ? "btn-primary" : "btn-secondary"}
          onClick={() => setIsCameraPaused(!isCameraPaused)}
        >
          {isCameraPaused ? <FiVideo size={20} /> : <FiVideoOff size={20} />}
          {isCameraPaused ? "Resume Camera" : "Pause Camera"}
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
      
      <div className="scanner-section">
        <header className="scanner-header">
          <div className="scanner-time">
            {currentTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
          <div className="scanner-date">
            {currentTime.toLocaleDateString([], { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
          </div>
        </header>

        <div className="webcam-container" style={{ position: 'relative' }}>
          {loginData && (
            <div className="identity-card">
              <div className="id-header">
                <img src={loginData.imageSrc} alt="Profile" className="id-avatar" />
                <div className="id-title">
                  <h2 className="id-name">{loginData.username}</h2>
                  <div className="id-status">
                    <FiCheck className="id-check-icon" />
                    <p className="id-role">Successfully Checked In</p>
                  </div>
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
              {!isCameraPaused ? (
                <FaceDetectionScanner
                  isRegistering={isRegistering}
                  isAdmin={isAdmin}
                  loginData={loginData}
                  isProcessing={isProcessing}
                  setIsProcessing={setIsProcessing}
                  setLoginData={setLoginData}
                  setScreenshotRef={setScannerRef}
                  livenessMode={livenessMode}
                />
              ) : (
                <div className="camera-paused-placeholder">
                  <FiVideoOff size={64} style={{ opacity: 0.5, marginBottom: '16px' }} />
                  <p style={{ fontSize: '20px', fontWeight: '500', color: '#94a3b8' }}>Camera is Paused</p>
                </div>
              )}
            </>
          ) : (
            <img className="img" src={lastFrame} alt="Captured frame" />
          )}
        </div>
      </div>
      {renderButtons()}
    </div>
  );
}

export default MasterComponent;
