# Hugging Face Spaces (Docker SDK): runs the Python server with real TimesFM on port 7860.
FROM python:3.11-slim
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH HF_HOME=/home/user/.cache/huggingface
WORKDIR /home/user/app
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --user numpy timesfm
# Bake the model weights into the image so the first forecast doesn't wait on a download.
RUN python -c "import timesfm; timesfm.TimesFM_2p5_200M_torch.from_pretrained('google/timesfm-2.5-200m-pytorch')"
COPY --chown=user . .
EXPOSE 7860
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "7860"]
