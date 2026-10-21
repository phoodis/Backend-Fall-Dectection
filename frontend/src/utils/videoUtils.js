export function isLocalPath(url) {
  if (!url) return false
  const urlLower = url.toLowerCase()
  return urlLower.startsWith('file://') ||
         (urlLower.match(/^[a-z]:[\\\/]/) && !urlLower.startsWith('http')) ||
         urlLower.startsWith('/') && !urlLower.startsWith('//')
}

export function convertToServerUrl(url) {
  if (!url) return url

  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url
  }

  if (url.startsWith('file://')) {
    const filePath = url.replace('file://', '')
    return convertPathToServerUrl(filePath)
  }

  if (isLocalPath(url)) {
    return convertPathToServerUrl(url)
  }

  return url
}

function convertPathToServerUrl(filePath) {
  const filename = filePath.split(/[\\\/]/).pop()
  return `/videos/${filename}`
}

export function getSuggestedServerUrl(originalPath) {
  if (!originalPath) return ''
  const filename = originalPath.split(/[\\\/]/).pop()
  return `http://localhost:3001/videos/${filename}`
}

export async function validateVideoUrl(url) {
  try {
    const response = await fetch(url, { method: 'HEAD' })
    return response.ok
  } catch (error) {
    console.error('Failed to validate video URL:', error)
    return false
  }
}

export function getVideoFileInfo(url) {
  if (!url) return { type: 'unknown', filename: '', extension: '' }

  const filename = url.split(/[\\\/]/).pop()
  const extension = filename.split('.').pop()?.toLowerCase() || ''

  let type = 'unknown'
  if (['mp4', 'webm', 'ogg'].includes(extension)) {
    type = 'video'
  } else if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(extension)) {
    type = 'image'
  } else if (url.includes('rtsp://') || url.includes('rtmp://')) {
    type = 'stream'
  }

  return {
    type,
    filename: filename || '',
    extension
  }
}

export function createVideoElement(url) {
  const video = document.createElement('video')
  video.src = url
  video.muted = true
  video.playsInline = true

  return new Promise((resolve, reject) => {
    video.addEventListener('loadedmetadata', () => {
      resolve({
        duration: video.duration,
        videoWidth: video.videoWidth,
        videoHeight: video.videoHeight,
        canPlay: true
      })
    })

    video.addEventListener('error', () => {
      reject(new Error(`Cannot load video: ${url}`))
    })

    setTimeout(() => {
      reject(new Error('Video loading timeout'))
    }, 10000)
  })
}
