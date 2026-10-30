using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;

[assembly: AssemblyTitle("SevenLabs")]
[assembly: AssemblyDescription("Private local voice cloning and transcription studio")]
[assembly: AssemblyCompany("SevenLabs")]
[assembly: AssemblyProduct("SevenLabs")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace SevenLabs.Launcher
{
    internal static class Program
    {
        private const string ResourcePrefix = "payload/";

        private static int Main()
        {
            Console.OutputEncoding = Encoding.UTF8;
            Console.Title = "SevenLabs";

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
                    Console.ForegroundColor = ConsoleColor.Green;
                    Console.WriteLine(firstSetup ? "SevenLabs — first-time setup" : "SevenLabs — updating components");
                    Console.ResetColor();
                    Console.WriteLine(firstSetup
                        ? "The AI engine will be downloaded once. This can take several minutes."
                        : "Required components changed and will be refreshed. Your data and models are preserved.");
                    Console.WriteLine();

                    int setupResult = RunPowerShell(appRoot, "setup.ps1");
                    if (setupResult != 0 || !File.Exists(python))
                    {
                        return StopWithError("Setup did not finish successfully. Check the message above, then open SevenLabs.exe again.");
                    }
                    File.WriteAllText(installedVersionFile, requirementsVersion);
                }

                return RunPowerShell(appRoot, "start.ps1");
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

            Console.WriteLine("Preparing SevenLabs...");
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
            startInfo.UseShellExecute = false;
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

        private static int StopWithError(string message)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine();
            Console.WriteLine("SevenLabs could not start");
            Console.ResetColor();
            Console.WriteLine(message);
            Console.WriteLine();
            Console.WriteLine("Press Enter to close.");
            Console.ReadLine();
            return 1;
        }
    }
}
