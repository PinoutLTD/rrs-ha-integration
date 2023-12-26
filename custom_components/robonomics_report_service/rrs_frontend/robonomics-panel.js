import "https://unpkg.com/wired-card@2.1.0/lib/wired-card.js?module";
import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

class ExamplePanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      route: { type: Object },
      panel: { type: Object },
      description: { type: String },
      phone: { type: String },
      uselogs: { type: Boolean },
      pictures: { type: Array },
      initialDescription: { type: String },
    };
  }

  constructor() {
    super();
    this.description = '';
    this.phone = '';
    this.uselogs = true;
    this.pictures = [];
    this.initialDescription = '';
  }

  connectedCallback() {
    super.connectedCallback();

    // Get the description parameter from the URL
    const urlParams = new URLSearchParams(window.location.search);
    this.initialDescription = urlParams.get('description') || '';
  }

  render() {

    if (!this.description && this.initialDescription) {
      this.description = this.initialDescription;
    }

    return html`
    <div
      class="header">
      Report an Issue
    </div>

    <textarea
      id="description"
      name="description"
      .value="${this.description}"
      rows="10"
      cols="100"
      @input="${this.handleDescriptionInput}"
      placeholder="Describe your problem..."
    ></textarea> <br>
    
    <input
      type="text"
      id="phone"
      name="phone"
      .value="${this.phone}"
      required
      minlength="4"
      maxlength="20"
      size="20"
      @input="${this.handlePhoneInput}"
      placeholder="Write your phone number..."
    /> <br>

    <div class="label-checkbox-container">
      <input
        type="checkbox"
        id="boolean-input"
        name="uselogs"
        .checked="${this.uselogs}"
        @change="${this.handleUselogsToggle}"
      > <br>
      <br>
      <br>
      <label for="boolean-input">Use Logs:</label>
      </div>

      <div
        class="drop-area"
        @dragover="${this.handleDragOver}"
        @drop="${this.handleDrop}"
      >
        <label for="picture" class="custom-button">Drag & Drop or Click to Upload Picture</label>
        <input
          type="file"
          id="picture"
          name="picture"
          accept="image/*"
          multiple
          class="visually-hidden"
          @change="${this.handlePictureUpload}"
        >
      </div> <br>

      ${this.pictures.length > 0
        ? html`
            <div>
              <h2>Uploaded Pictures:</h2>
              <div class="uploaded-pictures">
                ${this.pictures.map((picture, index) => html`
                  <div class="picture-container">
                    <img src="${picture}" alt="Uploaded Picture ${index + 1}" width="200" />
                    <button class="delete-button" @click="${() => this.deletePicture(index)}">Delete</button>
                  </div>
                `)}
              </div>
            </div>
          `
        : ''}
        


      <div>
        <button class="ha-styled-button" @click="${this.callService}">Call Service</button>
      </div> <br>

    `;
  }



  updated(changedProperties) {
    if (changedProperties.has("hass")) {
      this.setThemeVariables();
    }
  }

  setThemeVariables() {
    const root = this.shadowRoot || this;

    // Get theme variables from Home Assistant
    const primaryColor = this.hass.themes.darkMode
      ? this.hass.themes.darkPrimaryColor
      : this.hass.themes.lightPrimaryColor;

    // Define CSS custom properties
    root.style.setProperty("--primary-color", primaryColor);
  }

  deletePicture(index) {
    // Remove the picture at the specified index from the pictures array
    this.pictures.splice(index, 1);
    // Update the pictures property to trigger re-rendering
    this.pictures = [...this.pictures];
  }

  handleDragOver(event) {
    event.preventDefault();
  }

  handleDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    this.handleImageFile(files);
  }

  handlePictureUpload(event) {
    const files = event.target.files;
    this.handleImageFile(files);
  }

  handleImageFile(files) {

    // Loop through each selected file and read them
    Array.from(files).forEach((file) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        const pictureData = e.target.result;
        // Add the picture data to the pictures array
        this.pictures = [...this.pictures, pictureData];
      };
      reader.readAsDataURL(file);
    });
  }

  handleDescriptionInput(event) {
    this.description = event.target.value;
  }

  handlePhoneInput(event) {
    this.phone = event.target.value;
  }


  handleUselogsToggle(event) {
    this.uselogs = event.target.checked;
  }

  clearFields() {
    this.description = '';
    this.phone = '';
    this.uselogs = false;
    this.pictures = [];
  }

  callService() {
    const descriptionInput = this.shadowRoot.getElementById('description');

    if (descriptionInput.value.trim() === '') {
      // If the description field is empty, display an alert to the user
      alert('Please enter description of the problem.');
      return; // Exit the function, preventing the service call
    }
    const button = this.shadowRoot.querySelector('.ha-styled-button');
    button.disabled = true; // Disable the button

    this.hass.callService('robonomics_report_service', 'report_an_issue', {
      description: this.description,
      phone_number: this.phone,
      attach_logs: this.uselogs,
      picture: this.pictures
    })
      .then(() => {
        button.disabled = false; // Enable the button when the service call is completed
        this.clearFields();
      })
      .catch((error) => {
        console.error('Error calling service:', error);
        button.disabled = false; // Enable the button in case of an error
      });
  }

  static get styles() {
    return css`

    * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    }
    
    :host {
      background-color: var(--card-background-color);
      padding: 0px;
      font-family: Arial, sans-serif;
      display: block;
      max-width: 100%;
      margin: 0 auto; 
    }

    .picture-container {
      position: relative;
      display: inline-block;
      margin-right: 10px;
    }
    
    .delete-button {
      position: absolute;
      top: 5px;
      right: 5px;
      background-color: #ff4136;
      color: #fff;
      padding: 4px 8px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
    }
    
    .delete-button:hover {
      background-color: #d00000;
    }

    input[type="text"],
    textarea,
    button {
      max-width: 100%;
    }
    
    /* Header styles */
    h1 {
      font-size: 24px;
      color: #333;
      margin-bottom: 20px;
    }
    
    /* Text input styles */
    label,
    input[type="text"],
    textarea {
      display: block;
      margin-bottom: 0px;
      width: 98%;
      padding: 10px;
      border: 1px solid #ccc;
      border-radius: 4px;
      font-size: 16px;
      color: #555;
      font-family: 'Roboto', sans-serif;
      resize: none; 
      margin-left: 20px; 
      margin-top: 20px;  
    }
    
    /* Checkbox styles */
    .label-checkbox-container {
      display: flex;
      align-items: center;
      font-size: 16px;
      color: #333;
      margin-bottom: 10px;
      margin-left: 15px; 
    }
    
    /* Adjustments for the checkbox */
    label[for="boolean-input"] {
      margin-left: 5px; /* Add space between checkbox and label */
      margin-bottom: 0; /* Remove the bottom margin */
    }
    
    input[type="checkbox"] {
      margin-left: 0px; /* Add space between checkbox and following elements */
      margin-bottom: 0; /* Remove the bottom margin */
    }
    
    /* Button styles */
    button {
      background-color: var(--primary-color);
      color: #fff;
      padding: 10px 20px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 18px;
      margin-left: 20px; 
    }
    
    button:hover {
      background-color: var(--primary-color);
    }
    
    /* File input styles */
    .custom-button {
      background-color: var(--primary-color);
      color: #fff;
      padding: 10px 20px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 18px;
      display: inline-block;
      margin-right: 10px;
    }
    
    .visually-hidden {
      position: absolute;
      clip: rect(0 0 0 0);
      width: 1px;
      height: 1px;
      margin: -1px;
      padding: 0;
      overflow: hidden;
      border: 0;
    }
    
    /* Wired card styles */
    wired-card {
      background-color: var(--primary-color);
      padding: 16px;
      display: block;
      font-size: 18px;
      max-width: 600px;
      margin: 0 auto;
      border-radius: 4px;
      box-shadow: 0 0 8px rgba(0, 0, 0, 0.2);
    }

    .header {
      background-color: var(--app-header-background-color);
      font-weight: 200;
      color: var(--app-header-text-color, white); 
      font-size: 20px; /* Increase font size for the header */
      font-family: Arial;
      padding: 16px 20px; /* Increase padding for the header */
    }

    .ha-styled-button {
      background-color: var(--primary-color);
      color: #fff;
      padding: 10px 20px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 18px;
    }

    .ha-styled-button:disabled {
      background-color: #ccc;
      cursor: not-allowed;
    }

    @media screen and (max-width: 768px) {
      /* Adjust styles for screens up to 768px wide */
      .ha-styled-button {
        font-size: 16px;
      }

      label,
      input[type="text"],
      textarea,
      button {
        font-size: 14px;
      }

      .picture-container img {
        width: 100%;
        height: auto;
      }
    }

    @media screen and (max-width: 480px) {
      /* Adjust styles for screens up to 480px wide */
      .ha-styled-button {
        font-size: 14px;
      }

      label,
      input[type="text"],
      textarea,
      button {
        font-size: 12px;
      }
    }

    .checkbox-container {
      display: flex;
      align-items: center;
      margin-bottom: 10px; /* Add margin to separate from other fields */
    }
    
    /* Hidden native checkbox input */
    .checkbox-input {
      display: none;
    }

    `;
  }
}
customElements.define("robonomics-panel", ExamplePanel);