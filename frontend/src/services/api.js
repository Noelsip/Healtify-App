const API_BASE_URL = import.meta.env.API_BASE_URL ||'http://localhost:8000/api';

// Handle API response dan error
const handleResponse = async (response) => {
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
    }
    return response.json();
}

/**
 *Verify claim
 *POST /api/verify 
 */

export const verifyClaim = async (claimText) => {
  try {
    const response = await fetch(`${API_BASE_URL}/verify/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text: claimText }),
    });

    return await handleResponse(response);
  } catch (error) {
    console.error('Error verifying claim:', error);
    throw error;
  }
};

const createDispute = async (disputeData) => {
    try {
        const formData = new FormData();

        if (disputeData.claim_id) {
            formData.append('claim_id', disputeData.claim_id);
        }
        if (disputeData.claim_text) {
            formData.append('claim_text', disputeData.claim_text);
        }
        formData.append('reason', disputeData.reason);
        formData.append('reporter_name', disputeData.reporter_name || '');
        formData.append('reporter_email', disputeData.reporter_email || '');

        if (disputeData.supporting_doi) {
            formData.append('supporting_doi', disputeData.supporting_doi);
        }
        if (disputeData.supporting_file) {
            formData.append('supporting_file', disputeData.supporting_file);
        }
        if (disputeData.supporting_url) {
            formData.append('supporting_url', disputeData.supporting_url);
        }

        const response = await fetch(`${API_BASE_URL}/disputes/create`, {
            method: 'POST',
            body: formData
        });

        return await handleResponse(response);
    } catch (error) {
        console.error('Error creating dispute:', error);
        throw error;
    }
};

export default{
    verifyClaim, 
    handleResponse,
    createDispute
};