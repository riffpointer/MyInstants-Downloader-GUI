# MyInstants-Downloader
![BADGE](https://badgen.net/github/release/Shagnikpaul/MyInstants-Downloader-GUI)
![B2](https://img.shields.io/github/downloads/Shagnikpaul/MyInstants-Downloader-GUI/total)
<br>

A GUI utility to play and download sounds from [myinstants.com](https://www.myinstants.com/en/index/in/) made using python with least effort 💀. A great tool for s**tposters and content creators.


# RiffPointer Improvements
- Refreshed the app layout and reorganized the toolbar controls.
- Removed the startup autoplay behavior.
- Added batch download progress with skipping for already-downloaded files.
- Added a `Download Next Page` action after page downloads complete.
- Improved the empty search-results view with clearer messaging and search-term emphasis.
- Added settings support for download folder selection and theme switching.

# Screenshots
## Main Screen 
<img width="1366" height="728" alt="image" src="https://github.com/user-attachments/assets/0b55c19c-de55-4343-bae6-9ea76aa4cea1" />

## Search Function 
<img width="1366" height="728" alt="image" src="https://github.com/user-attachments/assets/59ebe344-be06-440d-84a8-c006668144b6" />

# How to run it ? (Currently only Windows supported.)
### PORTABLE .zip
Go to [Releases Page](https://github.com/Shagnikpaul/MyInstants-Downloader/releases/tag/release), download the latest `MyInstants_Downloader.zip` then extract the zip
wherever you want and execute the `main.exe` file in that directory.
### SETUP .exe
Go to [Releases Page](https://github.com/Shagnikpaul/MyInstants-Downloader/releases/tag/release), download the `setup.exe` and then run the installer like any normal software installer of Windows.

# How to use it ?
# ⚠ IMPORTANT NOTE / WARNING
It is recommended to turn down the volume of the application to somewhat low level because some sounds of myinstans.com are extremely loud and can literally kill you so consider lowering the volume first and then start using it 🤓
Click on the sound button to play that particular sound and download it by clicking the adjacent download button. 
> Downloaded files can be found in `downloads` folder present in the directory where files were extracted. (The one contaning the .exe file of this app) see the screenshot below for more info.


# Downloads Location
You can click on the <kbd>Open downloads folder</kbd> button to access the folder.All .mp3 files which you want to download by pressing the **download** button are saved in **downloads** folder present in the directory which has the `main.exe` file.
![SHOT](https://i.imgur.com/cuiyA9t.png)

# Libraries Used.
- Custom Tkinter for GUI
- Beautiful Soup for web scraping
- Python Requests for html extraction and file download.
- playsound library for playing sounds.
