export const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text);
    return { success: true, message: 'Copied!' };
  } catch (err) {
    console.error('Failed to copy:', err);
    return { success: false, message: 'Failed to copy' };
  }
};

export const shareContent = async (data) => {
  try {
    if (navigator.share) {
      await navigator.share({
        title: data.title || 'Healtify',
        text: data.text || '',
        url: data.url || window.location.href
      });
      return { success: true, message: 'Shared successfully' };
    } else {
      return await copyToClipboard(data.text || data.url);
    }
  } catch (err) {
    console.error('Failed to share:', err);
    return { success: false, message: 'Failed to share' };
  }
};