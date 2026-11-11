
  // Start Receipt Extraction using the backend upload-and-poll contract.
  const processReceiptFile = async (file) => {
    if (
      receiptScan.status === 'uploading' ||
      receiptScan.status === 'processing'
    ) {
      return;
    }

    if (!file) return;

    const allowedExtensions = ['.jpg', '.jpeg', '.png', '.webp', '.pdf'];
    const fileName = file.name || '';
    const fileExt = fileName.substring(fileName.lastIndexOf('.')).toLowerCase();

    const isAllowedExt = allowedExtensions.includes(fileExt);
    const isAllowedMime =
      file.type?.startsWith('image/') ||
      file.type === 'application/pdf';

    if (!isAllowedExt && !isAllowedMime) {
      setReceiptScan({
        status: 'error',
        file: null,
        previewUrl: null,
        progress: 0,
        stage: '',
        extractedData: null,
        confidence: null,
        error: 'File format not supported. Please upload a JPG, JPEG, PNG, WEBP, or PDF receipt.',
        warnings: [],
        editedFields: {},
        receiptId: null,
      });
      return;
    }

    const MAX_SIZE_BYTES = 10 * 1024 * 1024;

    if (file.size > MAX_SIZE_BYTES) {
      setReceiptScan({
        status: 'error',
        file: null,
        previewUrl: null,
        progress: 0,
        stage: '',
        extractedData: null,
        confidence: null,
        error: `File size (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds the 10 MB limit.`,
        warnings: [],
        editedFields: {},
        receiptId: null,
      });
      return;
    }

    // Release previous preview URL.
    if (receiptScan.previewUrl?.startsWith('blob:')) {
      try {
        URL.revokeObjectURL(receiptScan.previewUrl);
      } catch {
        // Ignore revoke errors.
      }
    }

    const previewUrl = URL.createObjectURL(file);

    setReceiptScan({
      status: 'uploading',
      file,
      previewUrl,
      progress: 15,
      stage: 'Uploading receipt to server...',
      extractedData: null,
      confidence: null,
      error: null,
      warnings: [],
      editedFields: {},
      receiptId: null,
    });

    try {
      // STEP 1: Upload receipt.
      const formData = new FormData();
      formData.append('file', file);

      const uploadResponse = await apiClient.request(
        API_ENDPOINTS.RECEIPTS.UPLOAD,
        {
          method: 'POST',
          body: formData,
          isFormData: true,
          timeout: 90000,
        }
      );

      if (!uploadResponse?.id) {
        throw new Error(
          'Receipt upload failed. The server did not return a receipt ID.'
        );
      }

      const receiptId = uploadResponse.id;

      setReceiptScan((prev) => ({
        ...prev,
        status: 'processing',
        progress: 35,
        stage: 'Analyzing your receipt...',
        receiptId,
      }));

      // STEP 2: Poll backend until extraction completes.
      const POLL_INTERVAL_MS = 2000;
      const MAX_POLL_ATTEMPTS = 45;

      const stageLabels = [
        { threshold: 40, label: 'Analyzing your receipt...' },
        { threshold: 55, label: 'Extracting merchant details...' },
        { threshold: 70, label: 'Identifying individual items...' },
        { threshold: 85, label: 'Calculating taxes and totals...' },
        { threshold: 95, label: 'Finalizing extraction results...' },
      ];

      let receiptData = null;

      for (let attempt = 1; attempt <= MAX_POLL_ATTEMPTS; attempt++) {
        await new Promise((resolve) =>
          setTimeout(resolve, POLL_INTERVAL_MS)
        );

        const progress = Math.min(
          35 + Math.round((attempt / MAX_POLL_ATTEMPTS) * 60),
          95
        );

        const currentStage =
          [...stageLabels]
            .reverse()
            .find((stage) => progress >= stage.threshold)?.label ||
          'Analyzing your receipt...';

        setReceiptScan((prev) => ({
          ...prev,
          progress,
          stage: currentStage,
        }));

        const pollData = await apiClient.request(
          API_ENDPOINTS.RECEIPTS.GET(receiptId),
          {
            method: 'GET',
            timeout: 10000,
          }
        );

        const extractionStatus = String(
          pollData.extraction_status || pollData.status || ''
        ).toUpperCase();

        if (extractionStatus === 'COMPLETED') {
          receiptData = pollData;
          break;
        }

        if (
          extractionStatus === 'FAILED' ||
          extractionStatus === 'ERROR'
        ) {
          throw new Error(
            Array.isArray(pollData.warnings) && pollData.warnings.length
              ? pollData.warnings.join(' ')
              : 'Receipt extraction failed. Please try again.'
          );
        }

        // PENDING or PROCESSING: continue polling.
      }

      // Extraction is still running.
      if (!receiptData) {
        setReceiptScan((prev) => ({
          ...prev,
          status: 'pending',
          progress: 95,
          stage: 'AI extraction is still processing...',
          receiptId,
        }));

        return;
      }

      // STEP 3: Map backend response into frontend data.
      const rawItems = Array.isArray(receiptData.items)
        ? receiptData.items
        : [];

      if (rawItems.length === 0) {
        throw new Error(
          'Receipt extraction completed, but no line items were found. Please review the image or upload a clearer receipt.'
        );
      }

      const defaultMembers =
        activeGroup?.members?.map((member) => member.userId || member.id)
          .filter(Boolean) ||
        [currentUser?.id].filter(Boolean);

      const formattedItems = rawItems.map((item, index) => {
        const unitPrice =
          item.unit_price != null ? Number(item.unit_price) : null;

        const totalPrice =
          item.total_price != null ? Number(item.total_price) : null;

        return {
          id: item.id || `item_${index + 1}`,
          name: item.item_name || `Item ${index + 1}`,
          item_name: item.item_name || `Item ${index + 1}`,
          quantity:
            item.quantity != null ? Number(item.quantity) : 1,
          price: totalPrice ?? unitPrice ?? 0,
          unitPrice,
          unit_price: unitPrice,
          total_price: totalPrice,
          assignedTo: [...defaultMembers],
        };
      });

      const merchant = receiptData.merchant_name || null;

      const subtotal =
        receiptData.subtotal != null
          ? Number(receiptData.subtotal)
          : null;

      const tax =
        receiptData.tax != null
          ? Number(receiptData.tax)
          : null;

      const receiptTotal =
        receiptData.total != null
          ? Number(receiptData.total)
          : null;

      const computedTotal =
        subtotal !== null && tax !== null
          ? Number((subtotal + tax).toFixed(2))
          : null;

      const finalTotal = receiptTotal ?? computedTotal;

      const warnings = Array.isArray(receiptData.warnings)
        ? [...receiptData.warnings]
        : [];

      if (
        subtotal !== null &&
        tax !== null &&
        receiptTotal !== null
      ) {
        const expectedTotal = Number((subtotal + tax).toFixed(2));

        if (Math.abs(receiptTotal - expectedTotal) > 0.05) {
          warnings.push(
            `Mathematical discrepancy: Subtotal + Tax = ${expectedTotal.toFixed(2)}, but receipt total is ${receiptTotal.toFixed(2)}. Please verify.`
          );
        }
      }

      const isFallback = Boolean(receiptData.is_fallback);

      const confidence =
        receiptData.confidence != null
          ? Number(receiptData.confidence)
          : null;

      const extraction = {
        receiptId,
        merchant,
        date: receiptData.receipt_date || null,
        category: 'General',
        currency: receiptData.currency || 'USD',
        subtotal,
        tax,
        tip: null,
        total: finalTotal,
        confidence,
        isFallback,
        items: formattedItems,
        warnings,
      };

      setReceiptScan({
        status: 'review',
        file,
        previewUrl,
        progress: 100,
        stage: 'Extraction complete',
        receiptId,
        extractedData: extraction,
        confidence,
        warnings,
        editedFields: {},
        error: null,
      });

    } catch (err) {
      const msg = err.message || '';
      const lowerMsg = msg.toLowerCase();

      let userFriendlyError =
        'Receipt extraction failed. Please try again.';

      if (
        lowerMsg.includes('unable to connect') ||
        lowerMsg.includes('unreachable') ||
        lowerMsg.includes('failed to fetch') ||
        lowerMsg.includes('network') ||
        lowerMsg.includes('econnrefused')
      ) {
        userFriendlyError =
          'Unable to connect to the receipt extraction service.';
      } else if (
        lowerMsg.includes('not a receipt') ||
        lowerMsg.includes('not appear to contain') ||
        lowerMsg.includes('invalid image') ||
        lowerMsg.includes('400')
      ) {
        userFriendlyError =
          'This image does not appear to contain a valid receipt.';
      } else if (
        lowerMsg.includes('blur') ||
        lowerMsg.includes('quality')
      ) {
        userFriendlyError =
          "We couldn't read this receipt clearly. Please upload a higher-quality image.";
      } else if (
        lowerMsg.includes('413') ||
        lowerMsg.includes('too large')
      ) {
        userFriendlyError =
          'The file is too large. Please upload an image under 10 MB.';
      } else if (
        lowerMsg.includes('422') ||
        lowerMsg.includes('unprocessable')
      ) {
        userFriendlyError =
          'The file could not be processed by the server. Please check the format and try again.';
      } else if (msg) {
        userFriendlyError = msg;
      }

      setReceiptScan((prev) => ({
        ...prev,
        status: 'error',
        stage: '',
        error: userFriendlyError,
        extractedData: null,
      }));
    }
  };
