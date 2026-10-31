using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Windows.Forms;

[assembly: AssemblyTitle("SevenLabs")]
[assembly: AssemblyDescription("Private local VoxCPM2 voice studio")]
[assembly: AssemblyCompany("SevenLabs")]
[assembly: AssemblyProduct("SevenLabs")]
[assembly: AssemblyVersion("2.0.0.0")]
[assembly: AssemblyFileVersion("2.0.0.0")]

namespace SevenLabs.Launcher
{
    internal static class Program
    {
        private const string ResourcePrefix = "payload/";

        [STAThread]
        private static int Main()
        {
            try
            {
                string appRoot = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "SevenLabs");

                Directory.CreateDirectory(appRoot);
                ExtractPayloadWhenChanged(appRoot);
                CreateDataFolders(appRoot);

                string python = Path.Combine(appRoot, ".venv", "Scripts", "python.exe");
                string requirementsVersion = ComputeFileHash(Path.Combine(appRoot, "requirements.txt"));
                string installedVersionFile = Path.Combine(appRoot, ".installed-requirements-version");
                bool firstSetup = !File.Exists(python);
                bool requirementsChanged = !File.Exists(installedVersionFile)
                    || File.ReadAllText(installedVersionFile).Trim() != requirementsVersion;

                if (firstSetup || requirementsChanged)
                {
                    int setupResult = RunPowerShell(appRoot, "setup.ps1");
                    if (setupResult != 0 || !File.Exists(python))
                    {
                        return StopWithError("Setup did not finish successfully. Check the message above, then open SevenLabs.exe again.");
                    }
                    File.WriteAllText(installedVersionFile, requirementsVersion);
                }

                return StartDesktopApp(appRoot);
            }
            catch (Exception error)
            {
                return StopWithError(error.Message);
            }
        }

        private static void ExtractPayloadWhenChanged(string appRoot)
        {
            Assembly assembly = Assembly.GetExecutingAssembly();
            string[] resources = assembly.GetManifestResourceNames()
                .Where(delegate(string name) { return name.StartsWith(ResourcePrefix, StringComparison.Ordinal); })
                .OrderBy(delegate(string name) { return name; }, StringComparer.Ordinal)
                .ToArray();

            if (resources.Length == 0)
            {
                throw new InvalidOperationException("The SevenLabs application files are missing from this launcher.");
            }

            string version = assembly.ManifestModule.ModuleVersionId.ToString("N");
            string versionFile = Path.Combine(appRoot, ".payload-version");
            if (File.Exists(versionFile) && File.ReadAllText(versionFile).Trim() == version)
            {
                return;
            }

            string rootWithSeparator = Path.GetFullPath(appRoot) + Path.DirectorySeparatorChar;
            foreach (string resource in resources)
            {
                string relativePath = resource.Substring(ResourcePrefix.Length)
                    .Replace('/', Path.DirectorySeparatorChar)
                    .Replace('\\', Path.DirectorySeparatorChar);
                string destination = Path.GetFullPath(Path.Combine(appRoot, relativePath));
                if (!destination.StartsWith(rootWithSeparator, StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException("An invalid application file path was detected.");
                }

                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using (Stream source = assembly.GetManifestResourceStream(resource))
                {
                    if (source == null)
                    {
                        throw new InvalidOperationException("Could not read " + resource + ".");
                    }
                    using (FileStream target = new FileStream(destination, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        source.CopyTo(target);
                    }
                }
            }

            File.WriteAllText(versionFile, version);
        }

        private static void CreateDataFolders(string appRoot)
        {
            foreach (string folder in new[] { "voices", "outputs", "models" })
            {
                Directory.CreateDirectory(Path.Combine(appRoot, "data", folder));
            }
        }

        private static string ComputeFileHash(string path)
        {
            using (SHA256 hash = SHA256.Create())
            using (FileStream stream = File.OpenRead(path))
            {
                return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", string.Empty);
            }
        }

        private static int RunPowerShell(string appRoot, string scriptName)
        {
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = "powershell.exe";
            startInfo.WorkingDirectory = appRoot;
            startInfo.UseShellExecute = true;
            startInfo.WindowStyle = ProcessWindowStyle.Normal;
            startInfo.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + Path.Combine(appRoot, scriptName) + "\"";

            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    throw new InvalidOperationException("Windows could not start PowerShell.");
                }
                process.WaitForExit();
                return process.ExitCode;
            }
        }

        private static int StartDesktopApp(string appRoot)
        {
            string pythonw = Path.Combine(appRoot, ".venv", "Scripts", "pythonw.exe");
            if (!File.Exists(pythonw))
            {
                return StopWithError("The SevenLabs desktop runtime is missing. Run the installer again to repair it.");
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = pythonw;
            startInfo.WorkingDirectory = appRoot;
            startInfo.Arguments = "-m app.desktop";
            startInfo.UseShellExecute = false;
            startInfo.CreateNoWindow = true;
            startInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
            startInfo.EnvironmentVariables["HF_HOME"] = Path.Combine(appRoot, "data", "models", "huggingface");
            startInfo.EnvironmentVariables["HF_HUB_CACHE"] = Path.Combine(appRoot, "data", "models", "huggingface", "hub");

            Process process = Process.Start(startInfo);
            if (process == null)
            {
                return StopWithError("Windows could not open the SevenLabs desktop window.");
            }
            return 0;
        }

        private static int StopWithError(string message)
        {
            MessageBox.Show(message, "SevenLabs could not start", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
